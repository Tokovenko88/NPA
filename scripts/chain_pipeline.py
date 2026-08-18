#!/usr/bin/env python3
"""
Chain Pipeline Processor
Sequentially applies multiple NPA amendments to a target NPA.

Each amendment is applied in chronological order (oldest number -> newest number).
For each step, the pipeline is executed and the intermediate result is saved
to the chain results folder.

Usage:
    python chain_pipeline.py <input_folder> [--target target_file.json] [--output work/chain_results] [--answers answers_base]

Input folder structure (flat):
    chain_input/
        target_npa.json          # Optional: explicitly named target
        269-ЗС.json              # Amendment 1
        380-ЗС.json              # Amendment 2
        stage_answers/
            269-ЗС/
                prompt_1_answer.json
                prompt_2_answer.json
                ...
            380-ЗС/
                prompt_1_answer.json
                ...

If target_npa.json is not present, the oldest NPA by date is used as target.
    If stage_answers/ subfolder is not present, pipeline runs with existing answers in work/answers/.
"""

import os
import sys
import json
import shutil
import subprocess
import argparse
import re
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Standard working directories
SOURCE_DIR = os.path.join(BASE_DIR, 'work', 'source')
ANSWERS_DIR = os.path.join(BASE_DIR, 'work', 'answers')
RESULT_DIR = os.path.join(BASE_DIR, 'work', 'results')
CHAIN_RESULTS_DIR = os.path.join(BASE_DIR, 'work', 'chain_results')
PIPELINE_SCRIPT = os.path.join(BASE_DIR, 'scripts', 'run_pipeline.py')
REPORT_PATH = os.path.join(BASE_DIR, 'scripts', 'report.md')


def log(msg, tag='info'):
    print(f"[{tag.upper()}] {msg}")


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_npa_number(npa_json):
    """Extract numeric part from npa_number for sorting."""
    number = npa_json.get('npa_number', '')
    digits = re.findall(r'\d+', number)
    if digits:
        return int(digits[0])
    return 0


def get_npa_date(npa_json):
    """Get the signing/publication date of an NPA."""
    for key in ('date_signed', 'date_pub', 'valid_from'):
        date_str = npa_json.get(key, '')
        if not date_str:
            continue
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
    return datetime.max


def scan_input_folder(input_folder):
    """
    Scan input folder for NPA JSON files.
    Returns (target_meta, amendment_metas) where amendment_metas is sorted by number ascending.
    """
    json_files = []
    for fname in os.listdir(input_folder):
        if fname.endswith('.json') and os.path.isfile(os.path.join(input_folder, fname)):
            json_files.append(fname)
    
    if not json_files:
        raise ValueError(f"No JSON files found in {input_folder}")
    
    files_meta = []
    for fname in json_files:
        path = os.path.join(input_folder, fname)
        try:
            data = load_json(path)
            files_meta.append({
                'filename': fname,
                'path': path,
                'data': data,
                'number': extract_npa_number(data),
                'date': get_npa_date(data),
            })
        except Exception as e:
            log(f"Failed to load {fname}: {e}", 'warning')
    
    if not files_meta:
        raise ValueError("No valid NPA JSON files found")
    
    # Identify target: explicit name wins, then oldest by date
    target_file = None
    for meta in files_meta:
        if meta['filename'].lower() == 'target_npa.json':
            target_file = meta
            break
    
    if target_file is None:
        files_meta.sort(key=lambda x: x['date'])
        target_file = files_meta[0]
    
    amendments = [m for m in files_meta if m['filename'] != target_file['filename']]
    amendments.sort(key=lambda x: (x['number'], x['date']))
    
    return target_file, amendments


def setup_working_dirs(target_path, source_path, answers_subdir=None):
    """Copy files to working directories and clean stage answers."""
    os.makedirs(SOURCE_DIR, exist_ok=True)
    target_dest = os.path.join(SOURCE_DIR, 'target_npa.json')
    shutil.copy2(target_path, target_dest)
    
    source_dest = os.path.join(SOURCE_DIR, 'source_npa.json')
    shutil.copy2(source_path, source_dest)
    
    if os.path.exists(ANSWERS_DIR):
        for fname in os.listdir(ANSWERS_DIR):
            fpath = os.path.join(ANSWERS_DIR, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)
    else:
        os.makedirs(ANSWERS_DIR, exist_ok=True)
    
    if answers_subdir and os.path.isdir(answers_subdir):
        for fname in os.listdir(answers_subdir):
            src = os.path.join(answers_subdir, fname)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(ANSWERS_DIR, fname))
        log(f"  Stage answers copied from: {answers_subdir}", 'info')


def run_single_pipeline(result_dir=None):
    """Run run_pipeline.py as subprocess and return result path."""
    cmd = [sys.executable, PIPELINE_SCRIPT]
    if result_dir:
        cmd.extend(['--result-dir', result_dir, '--keep-previous'])
    
    process = subprocess.Popen(
        cmd,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    
    for line in process.stdout:
        print(line, end='')
    
    process.wait()
    
    if process.returncode != 0:
        log(f"Pipeline exited with code {process.returncode}", 'error')
        return None
    
    search_dir = result_dir if result_dir else RESULT_DIR
    if not os.path.exists(search_dir):
        return None
    
    result_files = [f for f in os.listdir(search_dir) if f.endswith('.json')]
    if not result_files:
        log("Pipeline produced no result JSON", 'error')
        return None
    
    result_files.sort(key=lambda f: os.path.getmtime(os.path.join(search_dir, f)), reverse=True)
    return os.path.join(search_dir, result_files[0])


def run_chain(input_folder, explicit_target=None, output_dir=None, answers_base=None):
    """
    Run the chain pipeline.
    
    Args:
        input_folder: Folder containing target and amendment JSON files
        explicit_target: Optional filename in input_folder to use as target
        output_dir: Output directory for chain results
        answers_base: Base folder for stage answers per amendment
    """
    if output_dir is None:
        output_dir = CHAIN_RESULTS_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    log("=" * 60, 'info')
    log("CHAIN PIPELINE: Sequential NPA Amendment Application", 'info')
    log("=" * 60, 'info')
    log(f"Input folder : {input_folder}", 'info')
    log(f"Output folder: {output_dir}", 'info')
    
    target_file, amendments = scan_input_folder(input_folder)
    
    if explicit_target:
        target_file = next((m for m in [target_file] + amendments if m['filename'] == explicit_target), None)
        if target_file:
            amendments = [m for m in amendments if m['filename'] != explicit_target]
        else:
            log(f"Explicit target '{explicit_target}' not found, using auto-detected target", 'warning')
    
    if not amendments:
        log("No amendments found to apply", 'warning')
        return []
    
    log(f"Target NPA   : {target_file['filename']} "
        f"(number: {target_file['number']}, date: {target_file['date'].strftime('%Y-%m-%d')})", 'info')
    log(f"Amendments   : {len(amendments)}", 'info')
    for i, amend in enumerate(amendments, 1):
        log(f"  {i}. {amend['filename']} "
            f"(number: {amend['number']}, date: {amend['date'].strftime('%Y-%m-%d')})", 'info')
    
    current_target_path = target_file['path']
    chain_report = []
    
    for i, amendment in enumerate(amendments, 1):
        amendment_name = os.path.splitext(amendment['filename'])[0]
        amendment_path = amendment['path']
        
        log(f"\n{'=' * 60}", 'info')
        log(f"STEP {i}/{len(amendments)}: {amendment_name}", 'info')
        log(f"{'=' * 60}", 'info')
        
        answers_subdir = None
        if answers_base:
            for candidate in [
                os.path.join(answers_base, amendment_name),
                os.path.join(answers_base, amendment['filename']),
            ]:
                if os.path.isdir(candidate):
                    answers_subdir = candidate
                    break
        
        setup_working_dirs(current_target_path, amendment_path, answers_subdir)
        
        step_result_dir = os.path.join(CHAIN_RESULTS_DIR, f'step_{i:02d}_temp')
        os.makedirs(step_result_dir, exist_ok=True)
        
        result_path = run_single_pipeline(result_dir=step_result_dir)
        
        if result_path is None:
            log(f"STEP {i} FAILED: No result produced for {amendment_name}", 'error')
            chain_report.append({
                'step': i,
                'amendment': amendment_name,
                'status': 'failed',
                'error': 'Pipeline did not produce a result',
            })
            shutil.rmtree(step_result_dir, ignore_errors=True)
            continue
        
        result_data = load_json(result_path)
        result_filename = os.path.basename(result_path)
        chain_result_name = f"step_{i:02d}_{result_filename}"
        chain_result_path = os.path.join(output_dir, chain_result_name)
        save_json(chain_result_path, result_data)
        
        if os.path.exists(REPORT_PATH):
            step_report_path = os.path.join(output_dir, f"step_{i:02d}_report.md")
            shutil.copy2(REPORT_PATH, step_report_path)
        
        log(f"STEP {i} SUCCESS: {chain_result_path}", 'result')
        
        chain_report.append({
            'step': i,
            'amendment': amendment_name,
            'status': 'success',
            'result_file': chain_result_path,
        })
        
        current_target_path = chain_result_path
        shutil.rmtree(step_result_dir, ignore_errors=True)
    
    report_path = os.path.join(output_dir, 'chain_report.md')
    generate_chain_report(report_path, target_file, amendments, chain_report)
    log(f"\nChain report: {report_path}", 'info')
    
    return chain_report


def generate_chain_report(report_path, target_file, amendments, chain_report):
    lines = [
        "# Chain Pipeline Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Target NPA",
        f"- File: {target_file['filename']}",
        f"- Number: {target_file['data'].get('npa_number', '')}",
        f"- Date: {target_file['data'].get('date_signed', '')}",
        "",
        "## Amendments Applied (chronological order)",
    ]
    
    for report in chain_report:
        icon = "✅" if report['status'] == 'success' else "❌"
        lines.append(f"- Step {report['step']}: {icon} {report['amendment']}")
        if report['status'] == 'success':
            lines.append(f"  - Result: `{os.path.relpath(report['result_file'], BASE_DIR)}`")
        else:
            lines.append(f"  - Error: {report.get('error', 'Unknown')}")
    
    success_count = sum(1 for r in chain_report if r['status'] == 'success')
    lines.extend([
        "",
        "## Summary",
        f"- Total steps: {len(chain_report)}",
        f"- Successful: {success_count}",
        f"- Failed: {len(chain_report) - success_count}",
        "",
        f"## Results",
        f"Intermediate results saved in: `{os.path.relpath(CHAIN_RESULTS_DIR, BASE_DIR)}`",
        "",
    ])
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Chain Pipeline: sequentially apply multiple NPA amendments to a target'
    )
    parser.add_argument('input_folder', help='Folder containing target and amendment JSON files')
    parser.add_argument('--target', help='Explicit target filename in input folder (optional)')
    parser.add_argument('--output', help='Output directory for chain results (default: work/chain_results)')
    parser.add_argument('--answers', help='Base folder with stage answers per amendment (optional)')
    args = parser.parse_args()
    
    if not os.path.isdir(args.input_folder):
        log(f"Input folder not found: {args.input_folder}", 'error')
        sys.exit(1)
    
    run_chain(args.input_folder, args.target, args.output, args.answers)
