#!/usr/bin/env python3
"""
Chain Pipeline Processor
Sequentially applies multiple NPA amendments to a target NPA.

Each amendment is applied in chronological order using the canonical NPA date
parser. A failed step stops the chain by default; use --continue-on-error only
when intentionally accepting a non-contiguous chain.
"""

import argparse
import os
import re
import shutil
import sys
from datetime import datetime

from npa_processor._bootstrap import _bootstrap_project_root
from npa_processor.logging_utils import log

_bootstrap_project_root()

from npa_processor.domain.dates import parse_npa_date  # noqa: E402
from npa_processor.paths import (  # noqa: E402
    ANSWERS_DIR,
    CHAIN_RESULTS_DIR,
    REPORT_PATH,
    RESULTS_DIR,
    SOURCE_DIR,
    PROJECT_ROOT,
    load_json,
    save_json,
)
from npa_processor.processing.stage_answers import reset_stage4_counters  # noqa: E402
from scripts.run_pipeline import main as run_pipeline_main  # noqa: E402

BASE_DIR = PROJECT_ROOT


def extract_npa_number(npa_json):
    """Extract numeric part from npa_number for deterministic tie-breaking."""
    number = npa_json.get('npa_number', '')
    digits = re.findall(r'\d+', number)
    if digits:
        return int(digits[0])
    return 0


def get_npa_date(npa_json):
    """Get the NPA date using the canonical date parser."""
    for key in ('date_signed', 'date_pub', 'valid_from'):
        date_str = npa_json.get(key, '')
        if not date_str:
            continue
        try:
            return parse_npa_date(date_str, field_name=key)
        except ValueError:
            log(f"Invalid {key} in NPA {npa_json.get('npa_number', '')}: {date_str!r}", 'warning')
            continue
    return datetime.max.date()


def scan_input_folder(input_folder):
    """Scan input folder and return target plus chronologically sorted amendments."""
    json_files = [
        fname for fname in os.listdir(input_folder)
        if fname.endswith('.json') and os.path.isfile(os.path.join(input_folder, fname))
    ]

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

    target_file = next(
        (meta for meta in files_meta if meta['filename'].lower() == 'target_npa.json'),
        None,
    )
    if target_file is None:
        files_meta.sort(key=lambda x: (x['date'], x['number'], x['filename']))
        target_file = files_meta[0]

    amendments = [m for m in files_meta if m['filename'] != target_file['filename']]
    amendments.sort(key=lambda x: (x['date'], x['number'], x['filename']))
    return target_file, amendments


def setup_working_dirs(target_path, source_path, answers_subdir=None):
    """Copy files to working directories and clean stage answers."""
    os.makedirs(SOURCE_DIR, exist_ok=True)
    shutil.copy2(target_path, os.path.join(SOURCE_DIR, 'target_npa.json'))
    shutil.copy2(source_path, os.path.join(SOURCE_DIR, 'source_npa.json'))

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
    """Run run_pipeline.main in-process and return result path."""
    reset_stage4_counters()
    args = []
    if result_dir:
        args.extend(['--result-dir', result_dir, '--keep-previous'])

    try:
        run_pipeline_main(args)
    except SystemExit:
        pass
    except Exception as e:
        log(f"Pipeline raised exception: {e}", 'error')
        return None

    search_dir = result_dir if result_dir else RESULTS_DIR
    if not os.path.exists(search_dir):
        return None

    result_files = [f for f in os.listdir(search_dir) if f.endswith('.json')]
    if not result_files:
        log("Pipeline produced no result JSON", 'error')
        return None

    result_files.sort(key=lambda f: os.path.getmtime(os.path.join(search_dir, f)), reverse=True)
    return os.path.join(search_dir, result_files[0])


def run_chain(input_folder, explicit_target=None, output_dir=None, answers_base=None, continue_on_error=False):
    """Run the chain; stop on failure unless explicitly told to continue."""
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
            for candidate in (
                os.path.join(answers_base, amendment_name),
                os.path.join(answers_base, amendment['filename']),
            ):
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
            if not continue_on_error:
                log("Stopping chain after failed step (use --continue-on-error to override)", 'error')
                break
            continue

        result_data = load_json(result_path)
        result_filename = os.path.basename(result_path)
        chain_result_path = os.path.join(output_dir, f"step_{i:02d}_{result_filename}")
        save_json(chain_result_path, result_data)

        if os.path.exists(REPORT_PATH):
            shutil.copy2(REPORT_PATH, os.path.join(output_dir, f"step_{i:02d}_report.md"))

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
        "# Chain Pipeline Report", "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
        "## Target NPA",
        f"- File: {target_file['filename']}",
        f"- Number: {target_file['data'].get('npa_number', '')}",
        f"- Date: {target_file['data'].get('date_signed', '')}", "",
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
        "", "## Summary",
        f"- Total steps: {len(chain_report)}",
        f"- Successful: {success_count}",
        f"- Failed: {len(chain_report) - success_count}", "",
        "## Results",
        f"Intermediate results saved in: `{os.path.relpath(CHAIN_RESULTS_DIR, BASE_DIR)}`", "",
    ])
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main(args=None):
    parser = argparse.ArgumentParser(
        description='Chain Pipeline: sequentially apply multiple NPA amendments to a target'
    )
    parser.add_argument('input_folder', help='Folder containing target and amendment JSON files')
    parser.add_argument('--target', help='Explicit target filename in input folder (optional)')
    parser.add_argument('--output', help='Output directory for chain results (default: work/chain_results)')
    parser.add_argument('--answers', help='Base folder with stage answers per amendment (optional)')
    parser.add_argument(
        '--continue-on-error', action='store_true',
        help='Continue after a failed step (unsafe: later amendments may be applied to a non-contiguous result)',
    )
    parsed = parser.parse_args(args)

    if not os.path.isdir(parsed.input_folder):
        log(f"Input folder not found: {parsed.input_folder}", 'error')
        sys.exit(1)

    run_chain(
        parsed.input_folder,
        parsed.target,
        parsed.output,
        parsed.answers,
        continue_on_error=parsed.continue_on_error,
    )


if __name__ == '__main__':
    main()
