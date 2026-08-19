#!/usr/bin/env python3
"""
NPA Pipeline Processor
Executes stages 1-5 of the NPA JSON merging pipeline using the NPA-JSON-Processor
core functions (apply_change, rebuild_element_with_history) to produce output
matching the reference implementation exactly.
"""

import argparse
import copy
import os
import re
import time
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from npa_processor._bootstrap import _bootstrap_project_root

_bootstrap_project_root()

from npa_processor.learning import (  # noqa: E402
    DocumentHistory,
    LearningEngine,
    StructureVerifier,
)
from npa_processor.paths import (  # noqa: E402
    ANSWERS_DIR,
    LEARNING_DIR,
    REPORT_PATH,
    RESULTS_DIR,
    SOURCE_DIR,
    load_json,
    save_json,
    save_text,
)
from npa_processor.processing.change_applier import apply_change, apply_stage1_revocation, apply_stage2_date_change  # noqa: E402
from npa_processor.processing.html_utils import (  # noqa: E402
    extract_paragraphs_by_indices,
    get_full_element_html,
    remove_leading_number_from_html,
)
from npa_processor.processing.revision_builder import remove_empty_children  # noqa: E402
from npa_processor.processing.tree_utils import _find_target_element  # noqa: E402
from npa_processor.processing.ui_utils import (  # noqa: E402
    _find_existing_element_flexible,
    _make_new_revision,
    clean_number_for_filename,
    close_revision_date,
    find_item_by_id,
    get_date_for_filename,
    rebuild_element_with_history,
)


def log(msg, tag='info'):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
        print(safe_msg, flush=True)


def _validate_stage3_changes(changes, log_callback):
    """Validate stage-3 changes for known anti-patterns before applying."""
    errors = []
    if not changes:
        return errors

    for idx, change in enumerate(changes):
        ch_type = change.get('type', '').strip()
        structural = change.get('structural_element', '').strip()
        desc = change.get('description', '')

        if ch_type in ('change', 'delete'):
            if '<p>' in desc and '</p>' in desc and len(desc) > 500:
                errors.append(
                    f"Change #{idx} ({structural}): description содержит полный HTML "
                    f"({len(desc)} символов) — возможно, скопирован текст из изменяющего НПА"
                )
            if 'статья' in desc.lower() and 'часть' in desc.lower() and len(desc) > 1000:
                errors.append(
                    f"Change #{idx} ({structural}): description похож на фрагмент "
                    f"изменяющего НПА (упоминает статью и часть)"
                )

        elif ch_type in ('new_redaction', 'add'):
            if '<p>' in desc or '<' in desc:
                errors.append(
                    f"Change #{idx} ({structural}): description для "
                    f"{ch_type} содержит HTML теги, ожидаются номера абзацев"
                )

        if ch_type == 'delete':
            plural_delete_patterns = [
                r'пункты\s+\d+',
                r'подпункты\s+[а-я]',
                r'абзацы\s+\d+',
                r'части\s+\d+',
            ]
            is_plural_delete = any(re.search(pat, structural, re.IGNORECASE) for pat in plural_delete_patterns)
            if not is_plural_delete:
                continue
            if ',' in structural or ' и ' in structural.lower():
                errors.append(
                    f"Change #{idx} ({structural}): plural delete, возможно, "
                    f"не разбит на отдельные объекты"
                )

    return errors


def generate_result_filename(result_data, source_data):
    orig_npa_number = result_data.get('npa_number', '')
    orig_clean_num = clean_number_for_filename(orig_npa_number)
    orig_doc_type = result_data.get('doc_type', result_data.get('npa_type', 'law'))
    orig_date = get_date_for_filename(result_data, orig_doc_type)

    change_npa_number = source_data.get('npa_number', '')
    change_doc_type = source_data.get('doc_type', source_data.get('npa_type', 'law'))
    change_clean_num = clean_number_for_filename(change_npa_number)
    change_date = get_date_for_filename(source_data, change_doc_type)

    return f"{orig_clean_num}_{orig_date}_izm_{change_clean_num}_{change_date}.json"


def _load_stage_answers(name_prefix, log_callback=None):
    """Загрузить все ответы этапа, соответствующие префикексу (prompt_N_answer[_article_M])."""
    results = []
    candidates = []
    for fname in sorted(os.listdir(ANSWERS_DIR)):
        if fname.startswith(name_prefix) and fname.endswith('.json'):
            candidates.append(os.path.join(ANSWERS_DIR, fname))
    for path in candidates:
        try:
            data = load_json(path)
            if isinstance(data, list):
                results.extend(data)
        except Exception as e:
            msg = f"Warning: failed to load stage answer {path}: {e}"
            if log_callback:
                log_callback(msg, 'warning')
            else:
                print(msg)
    return results


def _attempt_recover_change(change, result_data, source, valid_from_dt, source_item_id,
                            rebuild_ids, log_callback,
                            learner, change_log_entry):
    """Попытаться восстановить проваленное изменение на основе истории самообучения.

    Использует проверенные маппинги и рекомендации по рекавери для переопределения
    resolution структурного элемента.
    """
    structural = change.get('structural_element', '').strip()
    suggestions = learner.get_suggestions_for_element(structural)
    reliable_id = learner.get_reliable_mapping(structural)
    recovered = False
    if reliable_id and reliable_id != change.get('_resolved_item_id'):
        log_callback(f"  RECOVERY: используем проверенный item_id '{reliable_id}' для '{structural}'", 'info')
        change['_resolved_item_id'] = reliable_id
        recovered = True
    else:
        for sug in suggestions:
            log_callback(f"  RECOVERY: согласно истории, для '{structural}' [{sug['category']}] "
                         f"предлагается: {sug['suggestion'][:120]}", 'info')
        if suggestions:
            target_elem = None
            try:
                target_elem = _find_existing_element_flexible(result_data, structural, log_callback)
            except ValueError:
                target_elem = None
            if target_elem:
                change['_resolved_item_id'] = target_elem['item_id']
                recovered = True
    if recovered:
        try:
            ok = apply_change(
                change=change, data=result_data, change_data=source, law_ref=None,
                general_valid_from=valid_from_dt, log_callback=log_callback,
                source_item_id=source_item_id,
                rebuild_ids=rebuild_ids, doc_type='law', extra_options=None,

                source_context_root=_find_target_element(source, result_data, log_callback, 'law')
                if result_data.get('npa_items_revision') else source,
                ambiguous_callback=None,
            )
            return ok
        except Exception as e:
            log_callback(f"  RECOVERY: исключение при повторном применении: {e}", 'error')
            return False
    return False


def _detect_and_apply_structural_reorganization(all_changes, data, valid_from_dt, source_npa_id, log_callback, source_data=None):
    """Detect and apply structural reorganization of an article into parts.

    ХАРАКТЕРНЫЙ ПРИЗНАК: изменение первого абзаца статьи добавляет нумерацию «1.»
    (или другую нумерацию части), что сигнализирует о реорганизации структуры.

    ПРАВИЛЬНАЯ СТРУКТУРА ПОСЛЕ РЕОРГАНИЗАЦИИ (см. target_npa.json):
    1. Статья: новая ревизия ТОЛЬКО с child_ref на часть 1 и часть 2 (без paragraph!)
    2. Часть 1: paragraph с изменённым текстом + child_ref на новые пункты (part_1_point_N)
    3. Старые пункты: закрыты valid_to, новые пункты созданы под часть 1 с новыми item_id
    4. Часть 2: новый контент из add-изменений
    5. item_children статьи заменяются на [part_1, part_2, ...]

    Returns True if reorganization was applied.
    """
    if not all_changes:
        return False

    reorganization_change = None
    target_article_id = None
    for change in all_changes:
        ch_type = change.get('type', '').strip()
        structural = change.get('structural_element', '').strip()
        desc = change.get('description', '')
        if ch_type == 'change' and 'статья' in structural.lower() and (re.search(r'заменить словами\s+[«"]1\.\s', desc) or re.search(r'дополнить словами\s+[«"]1\.\s', desc)):
            reorganization_change = change
            target_article_id = structural
            break

    if not reorganization_change:
        return False

    article_elem = None
    try:
        article_elem = _find_existing_element_flexible(data, target_article_id, log_callback)
    except ValueError:
        article_elem = None

    if not article_elem:
        return False

    direct_children = article_elem.get('item_children', [])
    if not direct_children:
        return False

    valid_from_str = valid_from_dt.strftime('%d.%m.%Y')
    valid_to_str = close_revision_date(valid_from_dt)
    article_id = article_elem.get('item_id', '')
    mod_by = reorganization_change.get('revision_number', source_npa_id)
    if not mod_by or mod_by == source_npa_id:
        mod_by = source_npa_id

    # 1. Закрываем текущую редакцию статьи
    revs = article_elem.get('revisions', [])
    active_idx = -1
    for i, rev in enumerate(revs):
        if rev.get('valid_to') in (None, ''):
            active_idx = i
            break
    if active_idx == -1 and revs:
        active_idx = len(revs) - 1
    if active_idx >= 0:
        revs[active_idx]['valid_to'] = valid_to_str

    # 2. Получаем изменённый первый абзац (он пойдёт в body части 1, а не статьи)
    old_article_rev = revs[active_idx] if active_idx >= 0 else {'body': []}
    old_paragraphs = [dict(b) for b in old_article_rev.get('body', []) if b.get('type') == 'paragraph']
    if not old_paragraphs:
        old_paragraphs = [{'type': 'paragraph', 'html_text': '', 'order': 1}]

    desc = reorganization_change.get('description', '')
    first_para_html = old_paragraphs[0].get('html_text', '')
    m = re.search(r'слова\s+[«"](.+?)[»"]\s+заменить словами\s+[«"](.+?)[»"]', desc)
    if m:
        old_text = m.group(1)
        new_text = m.group(2)
        first_para_html = first_para_html.replace(old_text, new_text, 1)
        modified_paragraph = {'type': 'paragraph', 'html_text': first_para_html, 'order': 1}
    else:
        modified_paragraph = old_paragraphs[0]

    # 3. Определяем, какие старые пункты активны в текущей ревизии
    active_child_ids = set()
    if active_idx >= 0:
        for b in revs[active_idx].get('body', []):
            if b.get('type') == 'child_ref':
                active_child_ids.add(b.get('item_id'))

    # 4. Создаём часть 1
    part1_id = f"{article_id}_part_1"
    part1_number = "1"
    part1_level = article_elem.get('item_level', 1) + 1

    # 4.1 Закрываем старые пункты и создаём НОВЫЕ пункты под часть 1
    # Только для пунктов, активных в текущей ревизии
    part1_children = []
    for old_child in direct_children:
        if old_child.get('item_id') not in active_child_ids:
            continue

        old_child_revs = old_child.get('revisions', [])
        for rev in old_child_revs:
            if rev.get('valid_to') in (None, ''):
                rev['valid_to'] = valid_to_str

        # Убираем trailing пунктуацию из номера для item_id
        child_num = str(old_child.get('item_number', '')).rstrip('.)')
        new_child_id = f"{part1_id}_{old_child['item_type']}_{child_num}"
        new_child = {
            'item_id': new_child_id,
            'item_type': old_child['item_type'],
            'item_number': old_child['item_number'],
            'item_level': part1_level + 1,
            'revisions': [{
                'valid_from': valid_from_str,
                'mod_type': 'change',
                'modified_by_id': mod_by,
                'body': [dict(b) for b in old_child_revs[-1].get('body', [])] if old_child_revs else [],
            }],
            'item_children': [],
        }
        part1_children.append(new_child)

    # 4.2 Создаём элемент части 1: paragraph + child_ref на новые пункты
    part1_body = [modified_paragraph]
    for idx, child in enumerate(part1_children):
        part1_body.append({'type': 'child_ref', 'item_id': child['item_id'], 'order': idx + 2})

    part1_rev = {
        'valid_from': valid_from_str,
        'mod_type': 'change',
        'modified_by_id': mod_by,
        'body': part1_body,
    }
    part1_elem = {
        'item_id': part1_id,
        'item_type': 'part',
        'item_number': part1_number,
        'item_level': part1_level,
        'revisions': [part1_rev],
        'item_children': part1_children,
    }

    # 5. Обрабатываем add-изменения: часть 2 и новые пункты
    add_changes = [c for c in all_changes if c.get('type', '').strip() == 'add' and c.get('structural_element', '').strip() == target_article_id]
    consumed_add_ids = set()
    new_parts = []
    part1_extra_children = []

    for change in add_changes:
        new_elem_type_map = {
            'пункт': 'point',
            'часть': 'part',
            'подпункт': 'subpoint',
            'абзац': 'paragraph',
            'статья': 'article',
            'приложение': 'appendix',
            'раздел': 'section',
        }
        ru_type = change.get('new', '')
        ru_type_base = ru_type.split()[0] if ru_type else ''
        sys_type = new_elem_type_map.get(ru_type_base)
        if not sys_type:
            continue

        num_match = re.search(r'(\d+[\.\d]*[⁰¹²³⁴⁵⁶⁷⁸⁹]*|[а-я]\)|I{1,3}[⁰¹²³⁴⁵⁶⁷⁸⁹]*)', ru_type)
        child_num = num_match.group(1) if num_match else ''

        source_elem = None
        def find_source(items, revision_number):
            for item in items:
                if item.get('item_id') == revision_number:
                    return item
                found = find_source(item.get('item_children', []), revision_number)
                if found:
                    return found
            return None

        source = source_data if source_data is not None else load_json(os.path.join(SOURCE_DIR, 'source_npa.json'))
        source_elem = find_source(source.get('npa_items_revision', []), change.get('revision_number'))

        if source_elem:
            source_html = get_full_element_html(source_elem, include_header=False)
            range_str = change.get('description', '').strip()
            cleaned_html = extract_paragraphs_by_indices(source_html, range_str)
            if not cleaned_html:
                cleaned_html = source_html
        else:
            cleaned_html = change.get('description', '')

        soup = BeautifulSoup(cleaned_html, 'html.parser')
        body_blocks = []
        order = 1
        for elem in soup.find_all(['p', 'table']):
            if elem.name == 'p':
                body_blocks.append({'type': 'paragraph', 'html_text': str(elem), 'order': order})
            elif elem.name == 'table':
                body_blocks.append({'type': 'table_fragment', 'html_text': str(elem), 'order': order})
            order += 1
        if not body_blocks and cleaned_html.strip():
            body_blocks = [{'type': 'paragraph', 'html_text': cleaned_html, 'order': 1}]

        if sys_type == 'part':
            new_part_id = f"{article_id}_part_{child_num}"
            new_part = {
                'item_id': new_part_id,
                'item_type': 'part',
                'item_number': child_num,
                'item_level': part1_level,
                'revisions': [{
                    'valid_from': valid_from_str,
                    'mod_type': 'add',
                    'modified_by_id': change.get('revision_number', mod_by),
                    'body': body_blocks,
                }],
                'item_children': [],
            }
            new_parts.append(new_part)
        else:
            new_child = {
                'item_id': f"{part1_id}_{sys_type}_{child_num}",
                'item_type': sys_type,
                'item_number': child_num,
                'item_level': part1_level + 1,
                'revisions': [{
                    'valid_from': valid_from_str,
                    'mod_type': 'add',
                    'modified_by_id': change.get('revision_number', mod_by),
                    'body': body_blocks,
                }],
                'item_children': [],
            }
            if body_blocks and body_blocks[0].get('type') == 'paragraph':
                body_blocks[0]['html_text'] = remove_leading_number_from_html(
                    body_blocks[0]['html_text'], str(child_num)
                )
            part1_extra_children.append(new_child)

        consumed_add_ids.add(id(change))

    # 6. Добавляем новые пункты в часть 1 (add-изменения перезаписывают старые с тем же номером)
    existing_nums = {c['item_number'] for c in part1_children}
    for new_child in part1_extra_children:
        if new_child['item_number'] not in existing_nums:
            part1_children.append(new_child)
            existing_nums.add(new_child['item_number'])

    part1_elem['item_children'] = part1_children

    # Обновляем body части 1: paragraph + child_ref на все пункты
    part1_body = [modified_paragraph]
    for idx, child in enumerate(part1_children):
        part1_body.append({'type': 'child_ref', 'item_id': child['item_id'], 'order': idx + 2})
    part1_elem['revisions'] = [{
        'valid_from': valid_from_str,
        'mod_type': 'change',
        'modified_by_id': mod_by,
        'body': part1_body,
    }]

    # 7. Обновляем тело статьи: ТОЛЬКО child_ref на часть 1 и новые части (без paragraph!)
    new_article_body = [
        {'type': 'child_ref', 'item_id': part1_id, 'order': 1},
    ]
    for idx, part in enumerate(new_parts):
        new_article_body.append({'type': 'child_ref', 'item_id': part['item_id'], 'order': idx + 2})

    new_article_rev = {
        'valid_from': valid_from_str,
        'mod_type': 'change',
        'modified_by_id': mod_by,
        'body': new_article_body,
    }
    revs.append(new_article_rev)
    article_elem['revisions'] = revs

    # 8. Заменяем прямых потомков статьи на часть 1 и новые части
    article_elem['item_children'] = [part1_elem] + new_parts

    # 9. Отмечаем обработанные изменения
    for change in all_changes:
        if id(change) in consumed_add_ids:
            change['_applied_by_reorganization'] = True
    if reorganization_change:
        reorganization_change['_applied_by_reorganization'] = True

    log_callback(f"  [REORGANIZATION] Статья {target_article_id} реорганизована: добавлены часть 1 и {len(new_parts)} новых частей")
    return True


def main(args=None):
    parser = argparse.ArgumentParser(description='NPA Pipeline Processor')
    parser.add_argument('--result-dir', help='Custom result directory (default: work/results)')
    parser.add_argument('--keep-previous', action='store_true',
                        help='Do not delete previous results in the result directory')
    parser.add_argument('--strict', action='store_true',
                        help='Abort on ambiguous element resolution or missing data')
    parser.add_argument('--source', help='Path to source NPA JSON (default: work/source/source_npa.json)')
    parser.add_argument('--target', help='Path to target NPA JSON (default: work/source/target_npa.json)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate and plan changes without writing output')
    parser.add_argument('--stage', type=int, choices=range(1, 6), default=None,
                        help='Run only up to specified stage (1-5)')
    parsed = parser.parse_args(args)

    result_dir = RESULTS_DIR
    if parsed.result_dir:
        result_dir = parsed.result_dir
        os.makedirs(result_dir, exist_ok=True)

    source_path = parsed.source if parsed.source else os.path.join(SOURCE_DIR, 'source_npa.json')
    target_path = parsed.target if parsed.target else os.path.join(SOURCE_DIR, 'target_npa.json')

    if parsed.dry_run:
        log("[DRY RUN] Режим проверки: изменения не будут записаны")

    if parsed.stage:
        log(f"[STAGE] Режим этапа: запуск до этапа {parsed.stage}")

    learner = LearningEngine()
    learner_stats = learner.get_stats()
    log(f"=== Самообучение: {learner_stats['total_runs']} запусков, "
        f"{learner_stats['total_changes_applied']} изменений, "
        f"{learner_stats['total_manual_corrections']} корректировок, "
        f"{learner_stats['reliable_mappings']} надёжных маппингов ===")

    if learner.get_failure_patterns(limit=3):
        log("  Последние паттерны провалов (извлечены из истории):")
        for p in learner.get_failure_patterns(limit=3):
            log(f"    - [{p['error_category']}] '{p['structural_element']}': "
                f"{p['count']} raz -> {p['suggestion'][:100]}")

    source = load_json(source_path)
    target = load_json(target_path)

    valid_from_date_str = source.get('valid_from', '')
    if not valid_from_date_str:
        valid_from_date_str = source.get('date_signed', '')
    if not valid_from_date_str:
        raise ValueError("Source NPA missing valid_from/date_signed")
    try:
        valid_from_dt = datetime.strptime(valid_from_date_str, '%d.%m.%Y').date()
    except (ValueError, TypeError):
        raise ValueError(f"Invalid date format in source NPA: {valid_from_date_str!r}") from None
    source_npa_id = str(source['npa_id'])
    target_npa_id = str(target.get('npa_id', ''))

    run_start = datetime.now()

    result_data = copy.deepcopy(target)
    history = DocumentHistory(LEARNING_DIR)
    history.set_source(target)
    history.snapshot('initial', result_data, {'label': 'target NPA before changes'})

    rebuild_ids = []
    errors = []
    warnings = []
    manual_corrections = []
    change_log = []

    source_context_root = _find_target_element(source, target, log, 'law')
    if source_context_root is None:
        source_context_root = source
        log("  Warning: _find_target_element returned None, using entire source NPA as context")

    log(f"  Source context root: {source_context_root.get('item_id', 'root')}")
    source_item_id = source_context_root.get('item_id')

    if not parsed.stage or parsed.stage >= 1:
        # ========== STAGE 1: Revocation Analysis ==========
        log("Stage 1: Revocation analysis.")
    stage1_changes = _load_stage_answers('prompt_1_answer', log)
    stage1_applied = 0
    stage1_failed = 0
    for change in stage1_changes:
        try:
            ok = apply_stage1_revocation(result_data, change, valid_from_dt, log, source_npa_id, strict=parsed.strict)
            if ok:
                stage1_applied += 1
                history.snapshot(f'after_stage1_revoke_{stage1_applied}', result_data,
                                 {'change': change, 'applied': True})
            else:
                stage1_failed += 1
                errors.append(f"Stage 1 failed: {change.get('structural_element_for_delete', '')}")
        except Exception as e:
            stage1_failed += 1
            errors.append(f"Stage 1 error: {str(e)}")
            import traceback
            traceback.print_exc()
    [{'type': 'delete',
                               'structural_element': c.get('structural_element_for_delete', ''),
                               'revision_number': None,
                               'description': ''} for c in stage1_changes]
    log(f"  Stage 1: {len(stage1_changes)} найдено, применено {stage1_applied}, провалено {stage1_failed}")

    if not parsed.stage or parsed.stage >= 2:
        # ========== STAGE 2: Dates Analysis ==========
        log("Stage 2: Dates and retroactive clauses analysis.")
    stage2_changes = _load_stage_answers('prompt_2_answer', log)
    stage2_applied = 0
    stage2_failed = 0
    for change in stage2_changes:
        try:
            ok = apply_stage2_date_change(result_data, change, valid_from_dt, log, source_npa_id, strict=parsed.strict)
            if ok:
                stage2_applied += 1
                history.snapshot(f'after_stage2_{stage2_applied}', result_data,
                                 {'change': change, 'applied': True})
            else:
                stage2_failed += 1
                errors.append(f"Stage 2 failed: {change.get('structural_element', '')}")
        except Exception as e:
            stage2_failed += 1
            errors.append(f"Stage 2 error: {str(e)}")
    log(f"  Stage 2: {len(stage2_changes)} найдено, применено {stage2_applied}, провалено {stage2_failed}")

    if not parsed.stage or parsed.stage >= 3:
        # ========== STAGE 3: Changes Extraction ==========
        all_changes = _load_stage_answers('prompt_3_answer', log)
    else:
        all_changes = []
    log(f"Stage 3: Loaded {len(all_changes)} changes from prompt answers.")

    # Post-stage-3 validation: catch anti-patterns before applying
    stage3_validation_errors = _validate_stage3_changes(all_changes, log)
    if stage3_validation_errors:
        log(f"Stage 3 validation: обнаружено {len(stage3_validation_errors)} проблем в изменениях")
        for err in stage3_validation_errors:
            log(f"  [VALIDATION] {err}", 'warning')
    else:
        log("Stage 3 validation: изменения выглядят корректно")

    # Consult reliable mappings BEFORE applying to pre-resolve structural elements
    reliable_mappings = learner.get_reliable_mappings(
        [c.get('structural_element', '').strip() for c in all_changes if c.get('structural_element')]
    )

    prompt_supplement = ""
    if not parsed.stage or parsed.stage >= 4:
        # ========== STAGE 4: Text Processing ==========
        prompt_supplement = learner.get_prompt_supplement(stage=4)
    if prompt_supplement:
        log("  Подключены обучающие примеры подсветки из learning/seed_examples.json")
    log("Stage 4: Using pre-generated answers from work/answers/ for change-type modifications.")

    # ========== STRUCTURAL REORGANIZATION ==========
    reorg_applied = _detect_and_apply_structural_reorganization(
        all_changes, result_data, valid_from_dt, source_npa_id, log, source_data=source
    )
    if reorg_applied:
        history.snapshot('after_reorganization', result_data, {'label': 'after structural reorganization'})

    change_type_counts = {}
    if not parsed.stage or parsed.stage >= 5:
        # ========== STAGE 5: Apply Changes ==========
        pass
    for change in all_changes:
        ct = change.get('type', 'unknown')
        change_type_counts[ct] = change_type_counts.get(ct, 0) + 1

    for change in all_changes:
        structural = change.get('structural_element', '').strip()
        ch_type = change.get('type', '').strip()
        structural_lower = structural.lower()

        if structural_lower == 'наименование':
            change['_resolved_item_id'] = '__наименование__'
        elif structural_lower == 'нпа':
            change['_resolved_item_id'] = None
        elif structural_lower == 'преамбула':
            change['_resolved_item_id'] = '__преамбула__'
        else:
            reliable_id = reliable_mappings.get(structural)
            if reliable_id is not None:
                change['_resolved_item_id'] = reliable_id
                log(f"  Используем проверенный маппинг для '{structural}' → {reliable_id}")
            else:
                target_elem = None
                try:
                    target_elem = _find_existing_element_flexible(result_data, structural, log)
                except ValueError as e:
                    target_elem = None
                    if parsed.strict:
                        log(f"  Stage 5: неоднозначность для '{structural}', отказ (strict): {e}", 'error')
                        change['_resolved_item_id'] = None
                        learner.record_mapping(structural, None, success=False, source_context=source_npa_id)
                        continue
                    log(f"  Неоднозначность для '{structural}', элемент не разрешён", 'warning')
                if target_elem:
                    change['_resolved_item_id'] = target_elem['item_id']
                else:
                    change['_resolved_item_id'] = None
                    learner.record_mapping(structural, None, success=False, source_context=source_npa_id)

    changes_applied = 0
    changes_failed = 0
    for change_idx, change in enumerate(all_changes):
        ch_type = change.get('type', '').strip()
        structural = change.get('structural_element', '').strip()
        applied = False
        error_msg = ''
        try:
            ok = apply_change(
                change=change,
                data=result_data,
                change_data=source,
                law_ref=None,
                general_valid_from=valid_from_dt,
                log_callback=log,
                source_item_id=source_item_id,
                rebuild_ids=rebuild_ids,
                doc_type='law',
                extra_options=None,
                source_context_root=source_context_root,
                ambiguous_callback=None,
            )
            if ok:
                changes_applied += 1
                applied = True
                resolved_id = change.get('_resolved_item_id') or None
                if resolved_id and not structural.lower().startswith('наименование'):
                    learner.record_mapping(structural, resolved_id, success=True,
                                           source_context=source_npa_id)
                if applied:
                    change_log.append({
                        'structural_element': structural, 'type': ch_type,
                        'applied': True, 'error': '',
                    })
                log(f"  Applied: {structural} ({ch_type})")
                history.snapshot(f'after_change_{change_idx}', result_data,
                                 {'structural_element': structural, 'type': ch_type, 'applied': True})
            else:
                changes_failed += 1
                error_msg = 'apply_change returned False'
                change_log.append({
                    'structural_element': structural, 'type': ch_type,
                    'applied': False, 'error': error_msg,
                })
                learner.record_mapping(structural, None, success=False, source_context=source_npa_id)
                log(f"  Failed: {structural}", 'error')
                # ---- CLOSED FEEDBACK: attempt recovery from learning ----
                recovered = _attempt_recover_change(
                    change, result_data, source, valid_from_dt, source_item_id,
                    rebuild_ids, log,
                    learner, change_log[-1],
                )
                if recovered:
                    changes_applied += 1
                    changes_failed -= 1
                    applied = True
                    if change_log:
                        change_log[-1].update({'applied': True, 'error': ''})
                    resolved_id = change.get('_resolved_item_id') or None
                    if resolved_id:
                        learner.record_recovery(structural, 'change_not_applied',
                                                're-resolve via learning', success=True,
                                                source_context=source_npa_id)
                    learner.record_mapping(structural, resolved_id, success=True,
                                           source_context=source_npa_id)
                    log(f"  RECOVERY succeeded: {structural}", 'result')
                    history.snapshot(f'after_change_{change_idx}_recovered', result_data,
                                     {'structural_element': structural, 'type': ch_type,
                                      'applied': True, 'recovered': True})
                else:
                    if change_log:
                        change_log[-1]['error_category'] = 'change_not_applied'
                    learner.record_recovery(structural, 'change_not_applied',
                                            're-resolve via learning', success=False,
                                            source_context=source_npa_id)
        except Exception as e:
            changes_failed += 1
            error_msg = str(e)
            import traceback
            traceback.print_exc()
            change_log.append({
                'structural_element': structural, 'type': ch_type,
                'applied': False, 'error': error_msg,
            })
            learner.record_mapping(structural, None, success=False, source_context=source_npa_id)

    log(f"\nStage 5: Applied {changes_applied} changes. Failed {changes_failed}. Rebuild IDs: {len(rebuild_ids)}")

    # ========== REBUILD ELEMENTS (two-pass, from _stage5_rebuild) ==========
    raw_ids = rebuild_ids
    unique_ids = list(dict.fromkeys(raw_ids))

    parent_map = {}
    def build_parent_map(items, parent_id=None):
        for item in items:
            item_id = item.get('item_id')
            if item_id:
                parent_map[item_id] = parent_id
            build_parent_map(item.get('item_children', []), item_id)
    build_parent_map(result_data.get('npa_items_revision', []))

    def is_ancestor_in_list(candidate_id, id_list):
        current_id = candidate_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            parent_id = parent_map.get(current_id)
            if parent_id in id_list:
                return True
            current_id = parent_id
        return False

    filtered_ids = []
    unique_set = set(unique_ids)
    for uid in unique_ids:
        elem = find_item_by_id(result_data, uid)
        if elem and (elem.get('_pending_new_redaction_html') or elem.get('_pending_html')) or not is_ancestor_in_list(uid, unique_set - {uid}):
            filtered_ids.append(uid)

    def get_depth(item_id):
        return item_id.count('_') if isinstance(item_id, str) else 0

    filtered_ids_sorted = sorted(filtered_ids, key=get_depth, reverse=True)
    log(f"Rebuild order (first pass): {filtered_ids_sorted}")

    rebuild_modified_by = source_npa_id

    def get_child_html_after_rebuild(child_id):
        child = find_item_by_id(result_data, child_id)
        if not child:
            return None
        revs = child.get('revisions', [])
        active_rev = None
        for rev in reversed(revs):
            if rev.get('valid_to') is None:
                active_rev = rev
                break
        if not active_rev:
            return None
        body_parts = []
        for block in active_rev.get('body', []):
            if block.get('type') == 'paragraph' or block.get('type') == 'table_fragment':
                body_parts.append(block.get('html_text', ''))
        if not body_parts:
            return None
        return '\n'.join(body_parts)

    def augment_pending_html(element_id):
        element = find_item_by_id(result_data, element_id)
        if not element:
            return
        if element.get('_pending_mod_type') not in ('change', 'new_redaction'):
            return
        has_changed_children = False
        def check_children_for_ids(item):
            nonlocal has_changed_children
            for child in item.get('item_children', []):
                if child.get('item_id') in raw_ids:
                    has_changed_children = True
                    return
                check_children_for_ids(child)
        check_children_for_ids(element)

        if has_changed_children:
            if element.get('_pending_new_redaction_html'):
                from bs4 import BeautifulSoup
                base_html = element['_pending_new_redaction_html']
                soup = BeautifulSoup(base_html, 'html.parser')
                child_ids_to_add = []
                def collect_child_ids(item):
                    for child in item.get('item_children', []):
                        if child.get('item_id') in raw_ids:
                            child_ids_to_add.append(child.get('item_id'))
                        collect_child_ids(child)
                collect_child_ids(element)
                for child_id in child_ids_to_add:
                    child_html = get_child_html_after_rebuild(child_id)
                    if not child_html:
                        continue
                    child_soup = BeautifulSoup(child_html, 'html.parser')
                    soup.append(child_soup)
                element['_pending_new_redaction_html'] = str(soup)
                log(f"  Augmented HTML for {element_id} with rebuilt child HTML")
            else:
                new_html = get_full_element_html(element, use_original_structure=False)
                if new_html:
                    from npa_processor.processing.html_utils import strip_number_from_element_html
                    new_html = strip_number_from_element_html(
                        new_html,
                        str(element.get('item_number', '')),
                        element.get('item_type', '')
                    )
                    element['_pending_new_redaction_html'] = new_html
                    log(f"  HTML for {element_id} updated with rebuilt children")

    for element_id in filtered_ids_sorted:
        element = find_item_by_id(result_data, element_id)
        if not element:
            log(f"  Element {element_id} not found for rebuild", 'error')
            continue

        augment_pending_html(element_id)

        ok = rebuild_element_with_history(
            result_data, element_id, valid_from_dt,
            rebuild_modified_by, 'law',
            log_callback=log
        )
        if ok:
            log(f"  Rebuilt: {element_id}")
        else:
            log(f"  Failed to rebuild: {element_id}", 'error')

    # Second pass for remaining pending
    def collect_pending_ids(items, acc):
        for item in items:
            if item.get('_pending_new_redaction_html') or item.get('_pending_html'):
                acc.append(item['item_id'])
            collect_pending_ids(item.get('item_children', []), acc)
        return acc

    remaining_pending = list(dict.fromkeys(collect_pending_ids(result_data.get('npa_items_revision', []), [])))
    if remaining_pending:
        remaining_pending_sorted = sorted(remaining_pending, key=get_depth, reverse=True)
        log(f"Second pass: rebuilding {len(remaining_pending_sorted)} elements: {remaining_pending_sorted}")
        for element_id in remaining_pending_sorted:
            element = find_item_by_id(result_data, element_id)
            if not element:
                continue

            augment_pending_html(element_id)

            ok = rebuild_element_with_history(
                result_data, element_id, valid_from_dt,
                rebuild_modified_by, 'law',
                log_callback=log
            )
            if ok:
                log(f"  Rebuilt (2nd pass): {element_id}")
            else:
                log(f"  Failed to rebuild (2nd pass): {element_id}", 'error')

    # ========== ADD revision_info ==========
    rev_info = {
        'revision_id': source_npa_id,
        'revision_number': source.get('npa_number', ''),
    }
    doc_type_change = source.get('doc_type', source.get('npa_type', 'law'))
    if doc_type_change == 'law':
        rev_info['revision_date_reg'] = source.get('date_signed', '')
    rev_info['revision_date_valid'] = valid_from_date_str
    rev_info['revision_url'] = source.get('npa_url', '')
    if 'revision_info' not in result_data:
        result_data['revision_info'] = []
    if not any(r.get('revision_id') == rev_info['revision_id'] for r in result_data['revision_info']):
        result_data['revision_info'].append(rev_info)
        log("Added revision_info for amending NPA")

    # ========== POST-PROCESSING ==========
    remove_empty_children(result_data)

    # ========== AUTO BUG FIXES (замкнутый цикл) ==========
    auto_fixes_applied = []

    def _fix_missing_valid_from(data, fallback_date, target_valid_from=None):
        fixed = []
        if target_valid_from is None:
            target_valid_from = data.get('valid_from') or data.get('date_signed') or data.get('date_pub') or fallback_date
        def recurse(items, level):
            for item in items:
                revs = item.get('revisions', [])
                for _idx, rev in enumerate(revs):
                    if not rev.get('valid_from'):
                        if rev.get('modified_by_id') or rev.get('mod_type'):
                            rev['valid_from'] = fallback_date
                        else:
                            rev['valid_from'] = target_valid_from
                        fixed.append(item.get('item_id'))
                recurse(item.get('item_children', []), level + 1)
        recurse(data.get('npa_items_revision', []), 1)
        head_rev = data.get('head_revision', [])
        if isinstance(head_rev, list):
            for rev in head_rev:
                if not rev.get('valid_from'):
                    if rev.get('modified_by_id') or rev.get('mod_type'):
                        rev['valid_from'] = fallback_date
                    else:
                        rev['valid_from'] = target_valid_from
                    fixed.append('head_revision')
        return fixed

    def _fix_duplicate_item_ids(data):
        seen = {}
        duplicates = []
        def recurse(items):
            for item in items:
                iid = item.get('item_id')
                if not iid:
                    recurse(item.get('item_children', []))
                    continue
                if iid in seen:
                    base = iid
                    n = 1
                    new_id = f"{base}_double_{n}"
                    while new_id in seen:
                        n += 1
                        new_id = f"{base}_double_{n}"
                    item['item_id'] = new_id
                    seen[new_id] = True
                    duplicates.append((base, new_id))
                else:
                    seen[iid] = True
                recurse(item.get('item_children', []))
        recurse(data.get('npa_items_revision', []))
        return duplicates

    def _fix_missing_child_refs(data):
        fixed = []
        def recurse(items):
            for item in items:
                children = item.get('item_children', [])
                if not children:
                    recurse(item.get('item_children', []))
                    continue
                revs = item.get('revisions', [])
                active_rev = None
                for rev in reversed(revs):
                    if rev.get('valid_to') in (None, ''):
                        active_rev = rev
                        break
                if not active_rev and revs:
                    active_rev = revs[-1]
                if not active_rev:
                    recurse(item.get('item_children', []))
                    continue
                body = active_rev.get('body', [])
                existing_refs = {b.get('item_id') for b in body if isinstance(b, dict) and b.get('type') == 'child_ref'}
                for child in children:
                    cid = child.get('item_id')
                    if cid and cid not in existing_refs:
                        body.append({'type': 'child_ref', 'item_id': cid, 'order': len(body) + 1})
                        fixed.append(cid)
                active_rev['body'] = body
                recurse(item.get('item_children', []))
        recurse(data.get('npa_items_revision', []))
        return fixed

    def _fix_broken_child_refs(data):
        id_set = set()
        def collect_ids(items):
            for item in items:
                iid = item.get('item_id')
                if iid:
                    id_set.add(iid)
                collect_ids(item.get('item_children', []))
        collect_ids(data.get('npa_items_revision', []))
        fixed = []
        def recurse(items):
            for item in items:
                revs = item.get('revisions', [])
                active_rev = None
                for rev in reversed(revs):
                    if rev.get('valid_to') in (None, ''):
                        active_rev = rev
                        break
                if not active_rev and revs:
                    active_rev = revs[-1]
                if active_rev:
                    body = active_rev.get('body', []) if isinstance(active_rev.get('body'), list) else []
                    new_body = []
                    changed = False
                    for block in body:
                        if isinstance(block, dict) and block.get('type') == 'child_ref':
                            ref_id = block.get('item_id')
                            if ref_id and ref_id not in id_set:
                                changed = True
                                fixed.append(ref_id)
                                continue
                        new_body.append(block)
                    if changed:
                        active_rev['body'] = new_body
                recurse(item.get('item_children', []))
        recurse(data.get('npa_items_revision', []))
        return fixed

    def _fix_invalid_item_levels(data):
        fixed = []
        def recurse(items, expected_level):
            for item in items:
                actual = item.get('item_level')
                if actual is not None and actual != expected_level:
                    item['item_level'] = expected_level
                    fixed.append(item.get('item_id'))
                recurse(item.get('item_children', []), expected_level + 1)
        recurse(data.get('npa_items_revision', []), 1)
        return fixed

    def _apply_bug_fixes(data, source, target, learner):
        nonlocal auto_fixes_applied
        v_before = StructureVerifier().verify(data, source_data=source)
        fixes = []
        fallback_date = valid_from_date_str or source.get('valid_from') or source.get('date_signed') or source.get('date_pub')
        target_valid_from = data.get('valid_from') or data.get('date_signed') or data.get('date_pub') or fallback_date

        fixed_ids = _fix_missing_valid_from(data, fallback_date, target_valid_from)
        if fixed_ids:
            fixes.append({
                'bug': 'revision_valid_from_missing',
                'fix': f"Установлен valid_from='{fallback_date}' для {len(fixed_ids)} элементов",
                'applied_to': fixed_ids[:10],
            })

        dups = _fix_duplicate_item_ids(data)
        if dups:
            fixes.append({
                'bug': 'item_id_duplicate',
                'fix': f"Дублирующимся item_id добавлен суффикс _double_N ({len(dups)} шт.)",
                'applied_to': [d[1] for d in dups[:10]],
            })

        missing_refs = _fix_missing_child_refs(data)
        if missing_refs:
            fixes.append({
                'bug': 'child_ref_missing',
                'fix': f"Добавлены отсутствующие child_ref в body родителей ({len(missing_refs)} шт.)",
                'applied_to': missing_refs[:10],
            })

        broken_refs = _fix_broken_child_refs(data)
        if broken_refs:
            fixes.append({
                'bug': 'child_ref_broken',
                'fix': f"Удалены битые child_ref, ссылающиеся на несуществующие item_id ({len(broken_refs)} шт.)",
                'applied_to': broken_refs[:10],
            })

        fixed_levels = _fix_invalid_item_levels(data)
        if fixed_levels:
            fixes.append({
                'bug': 'item_level_invalid',
                'fix': f"Пересчитан item_level для {len(fixed_levels)} элементов",
                'applied_to': fixed_levels[:10],
            })

        v_after = StructureVerifier().verify(data, source_data=source)

        for fix in fixes:
            learner.record_bug_fix(
                bug_description=fix['bug'],
                fix_description=fix['fix'],
                applied_to=fix['applied_to'],
                verification_before=v_before.to_dict().get('stats', {}),
                verification_after=v_after.to_dict().get('stats', {}),
                source_npa_id=source_npa_id,
                target_npa_id=target_npa_id,
                success=True,
            )
            log(f"  AUTO-FIX [{fix['bug']}]: {fix['fix']}", 'result')
            auto_fixes_applied.append(fix)

        return v_after

    _apply_bug_fixes(result_data, source, target, learner)

    # ========== SAVE RESULT ==========
    if not parsed.keep_previous:
        for fname in os.listdir(result_dir):
            if fname.endswith('.json'):
                old_path = os.path.join(result_dir, fname)
                try:
                    os.remove(old_path)
                    log(f"  Removed old result file: {fname}")
                except Exception as e:
                    log(f"  Warning: could not remove old result file {fname}: {e}", 'warning')

    filename = generate_result_filename(result_data, source)
    result_path = os.path.join(result_dir, filename)

    if parsed.dry_run:
        log(f"[DRY RUN] Результат был бы сохранён в: {result_path}")
        log(f"[DRY RUN] Изменений применено: {changes_applied}, провалено: {changes_failed}")
    else:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                if os.path.exists(result_path):
                    os.remove(result_path)
                save_json(result_path, result_data)
                log(f"Result saved to: {result_path}")
                break
            except PermissionError as e:
                log(f"Error saving (attempt {attempt}/{max_attempts}): {e}")
                if attempt < max_attempts:
                    time.sleep(1.5)
                else:
                    errors.append(f"Could not save result file: {e}")

    # ========== POST-REBUILD HISTORY SNAPSHOT ==========
    history.snapshot('after_rebuild', result_data,
                     {'label': 'document after rebuild pass', 'rebuild_ids': rebuild_ids})

    # ========== COMPREHENSIVE VERIFICATION ==========
    log("\n=== VERIFICATION (самообучающийся движок) ===")
    verifier = StructureVerifier()
    remaining_changes = [c for c in all_changes if not c.get('_applied_by_reorganization')]
    verification = verifier.verify(
        data=result_data,
        changes=remaining_changes,
        source_data=source,
        change_log=change_log,
    )
    vdict = verification.to_dict()

    if vdict['passed']:
        log("  Верификация пройдена: все проверки целостности и ожидаемых изменений успешны.")
    else:
        log("  Верификация выявила ошибки:")
    for err in vdict['errors']:
        log(f"    [ОШИБКА] {err['category']} — {err['message']}", 'error')
    for warn in vdict['warnings']:
        log(f"    [ПРЕДУПРЕЖДЕНИЕ] {warn['category']} — {warn['message']}", 'warning')

    # Переводим серьёзные ошибки верификации в список errors
    for err in vdict['errors']:
        errors.append(f"VERIFY[{err['category']}]: {err['message']}")
    for warn in vdict['warnings']:
        warnings.append(f"VERIFY[{warn['category']}]: {warn['message']}")

    # Сохранить проверенный итог в историю
    history.snapshot('after_verification', result_data,
                     {'label': 'document after verification', 'verification': vdict['stats']})

    # ---------- Закрытый цикл: анализ провалов → улучшение алгоритма ----------
    failure_patterns = learner.get_failure_patterns(limit=10)
    if failure_patterns:
        log("\n  АНАЛИЗ ПАТТЕРНОВ ПРОВАЛОВ (из истории самообучения):")
        for p in failure_patterns:
            log(f"    [{p['error_category']}] '{p['structural_element']}': "
                f"{p['count']} раз → {p['suggestion']}")

    # ---------- Запись в самообучение ----------
    elapsed = (datetime.now() - run_start).total_seconds()
    learner.record_verification_result(
        run_timestamp=run_start.isoformat(),
        source_npa_id=source_npa_id,
        target_npa_id=target_npa_id,
        verification=vdict,
    )

    # Записать исходы каждого изменения в самообучение
    for outcome in vdict.get('change_outcomes', []):
        cat = None
        for err in vdict['errors']:
            if err.get('change_index') == outcome['change_index']:
                cat = err['category']
                break
        learner.record_change_outcome(
            structural_element=outcome['structural_element'],
            change_type=outcome['type'],
            applied=outcome['passed'],
            structurally_valid=outcome['passed'],
            error_category=cat or ('change_not_applied' if not outcome['passed'] else None),
            error_message=outcome['reason'],
            source_context=source_npa_id,
        )

    # Записать характерные примеры ошибок
    for err in vdict.get('errors', []):
        learner.record_error_example(
            structural_element=err.get('structural_element', ''),
            error_category=err.get('category', ''),
            error_message=err.get('message', ''),
            context={
                'change_index': err.get('change_index'),
                'element': err.get('element'),
                'severity': err.get('severity'),
                'remediation': err.get('remediation'),
            },
            source_npa_id=source_npa_id,
            target_npa_id=target_npa_id,
        )
    for warn in vdict.get('warnings', []):
        learner.record_error_example(
            structural_element=warn.get('structural_element', ''),
            error_category=warn.get('category', ''),
            error_message=warn.get('message', ''),
            context={
                'change_index': warn.get('change_index'),
                'element': warn.get('element'),
                'severity': warn.get('severity'),
                'remediation': warn.get('remediation'),
            },
            source_npa_id=source_npa_id,
            target_npa_id=target_npa_id,
        )

    status = "Успешно" if not errors else "С ошибками"
    changes_by_type = {t: change_type_counts.get(t, 0) for t in
                       ('add', 'delete', 'change', 'new_redaction')}
    report = f"""# Отчёт об обработке НПА

## Исходные данные
- Изменяющий НПA: {source.get('npa_number', '')} от {source.get('date_pub', '')}
- Целевой НПA: {target.get('npa_number', '')} от {target.get('date_pub', '')}

## Этап 1: Утрата силы
- Найдено указаний: {len(stage1_changes)}
- Применено: {stage1_applied}
- Ошибки: {stage1_failed}

## Этап 2: Даты и ретроактивность
- Найдено указаний: {len(stage2_changes)}
- Применено: {stage2_applied}
- Ошибки: {stage2_failed}

## Этап 3: Изменения
- Найдено изменений: {len(all_changes)}
  - add: {changes_by_type.get('add', 0)}
  - delete: {changes_by_type.get('delete', 0)}
  - change: {changes_by_type.get('change', 0)}
  - new_redaction: {changes_by_type.get('new_redaction', 0)}
- Применено: {changes_applied}
- Не применено: {changes_failed}
- Ошибок верификации: {vdict['stats']['total_errors']}
- Предупреждений: {vdict['stats']['total_warnings']}
"""
    if errors:
        report += "- Список ошибок:\n"
        for err in errors:
            report += f"  - {err}\n"
    if warnings:
        report += "- Предупреждения:\n"
        for w in warnings:
            report += f"  - {w}\n"

    report += f"""
## Этап 4: HTML-обработка
- Обработано элементов: {sum(1 for c in all_changes if c.get('type') == 'change')}

## Этап 5: Перестройка
- Элементов на перестройку: {len(filtered_ids_sorted)}
    - История документа сохранена в: learning/history/{history.run_id}/

## Верификация структуры (самообучение)
- Статус: {'ПРОЙДЕНА' if vdict['passed'] else 'С ОШИБКАМИ'}
- Изменений проверено: {vdict['stats']['changes_total']}
- Изменений прошло проверку: {vdict['stats']['changes_passed']}
- Изменений не прошло проверку: {vdict['stats']['changes_failed']}

## Исправления багов (агент)
- Применено автоматических исправлений: {len(auto_fixes_applied)}
"""
    if auto_fixes_applied:
        for fix in auto_fixes_applied:
            report += f" - [{fix['bug']}]: {fix['fix']}\n"
    else:
        report += " - Автоматических исправлений не потребовалось\n"

    report += f"""
## Характерные примеры ошибок (последние 10)
- Всего зафиксировано примеров: {vdict['stats']['total_errors'] + vdict['stats']['total_warnings']}
"""
    recent_examples = learner.get_error_examples(limit=10)
    if recent_examples:
        for ex in recent_examples[:10]:
            report += f" - [{ex['error_category']}] {ex['structural_element']}: {ex['error_message'][:100]}\n"
    else:
        report += " - Нет зафиксированных примеров\n"

    report += f"""
## Итог
- Статус: {status}
- Итоговый файл: work/results/{filename}
- Время выполнения: {elapsed:.1f}с
"""

    report_path = REPORT_PATH
    save_text(report_path, report)

    # Print concise chat summary
    print("\n" + "="*60)
    print("PIPELINE COMPLETED")
    print("="*60)
    print(f"Status: {status}")
    print(f"Source: {source.get('npa_number', '')} ({source.get('date_pub', '')})")
    print(f"Target: {target.get('npa_number', '')} ({target.get('date_pub', '')})")
    print(f"Changes applied: {changes_applied}")
    print(f"Changes failed: {changes_failed}")
    print(f"Output: {result_path}")
    print(f"Report: {report_path}")
    print(f"Verification: {'PASSED' if vdict['passed'] else 'FAILED'}")
    if errors:
        print(f"Warnings/Errors: {len(errors)}")
    print("="*60)

    report_json_path = os.path.join(result_dir, filename.replace('.json', '_report.json'))
    report_data = {
        'status': status,
        'source_npa': {'number': source.get('npa_number', ''), 'date_pub': source.get('date_pub', '')},
        'target_npa': {'number': target.get('npa_number', ''), 'date_pub': target.get('date_pub', '')},
        'stage1': {'found': len(stage1_changes), 'applied': stage1_applied, 'failed': stage1_failed},
        'stage2': {'found': len(stage2_changes), 'applied': stage2_applied, 'failed': stage2_failed},
        'stage3': {'found': len(all_changes), 'applied': changes_applied, 'failed': changes_failed,
                    'by_type': change_type_counts},
        'stage4': {'processed': sum(1 for c in all_changes if c.get('type') == 'change')},
        'stage5': {'rebuild_count': len(filtered_ids_sorted)},
        'verification': {'passed': vdict['passed'], 'total_errors': vdict['stats']['total_errors'],
                         'total_warnings': vdict['stats']['total_warnings'],
                         'changes_total': vdict['stats']['changes_total'],
                         'changes_passed': vdict['stats']['changes_passed'],
                         'changes_failed': vdict['stats']['changes_failed']},
        'auto_fixes': auto_fixes_applied,
        'errors': errors,
        'warnings': warnings,
        'change_log': change_log,
        'result_file': f"work/results/{filename}",
        'elapsed_seconds': elapsed,
    }
    save_json(report_json_path, report_data)
    log(f"Report JSON saved to: {report_json_path}")

    # ========== LEARNING ==========
    learner.record_detailed_run(
        source_npa_id=source_npa_id,
        target_npa_id=target_npa_id,
        changes_applied=changes_applied,
        changes_failed=changes_failed,
        manual_corrections=manual_corrections,
        notes=status,
        changes_detail=change_log,
        verification=vdict,
        elapsed_seconds=elapsed,
    )
    learner.record_run(
        source_npa_id=source_npa_id,
        target_npa_id=target_npa_id,
        changes_applied=changes_applied,
        changes_failed=changes_failed,
        manual_corrections=manual_corrections,
        notes=status,
    )
    log(f"\n=== Самообучение: {learner.summarize_for_agent()} ===")

    log(f"\nPipeline completed. Applied {changes_applied} changes.")
    log(f"Result saved to: {result_path}")
    log(f"Report saved to: {report_path}")
    log(f"Verification passed: {vdict['passed']}")
    if errors:
        log(f"Warnings/Errors: {len(errors)} (verification errors: {vdict['stats']['total_errors']})")


if __name__ == '__main__':
    main()
