"""Применение изменений к документу."""

import copy
import re
from datetime import datetime

from bs4 import BeautifulSoup

from npa_processor.constants import TYPE_TO_RUSSIAN
from npa_processor.processing.ai_utils import get_stage4_answer
from npa_processor.processing.element_finder import (
    _extract_paragraph_order,
    _resolve_modified_by_ids,
    find_item_by_revision_number,
)
from npa_processor.processing.html_utils import (
    _correct_table_highlights,
    _extract_replacement_pairs,
    _verify_ai_highlights_for_replacements,
    clean_and_unwrap_html,
    clean_description_html,
    compute_highlights_from_html_diff,
    extract_paragraphs_by_indices,
    get_current_head,
    get_full_element_html,
    parse_ai_response_for_prompt4,
    parse_structural_tokens,
    remove_leading_number_from_html,
    split_html_to_paragraphs,
    strip_number_from_element_html,
)
from npa_processor.processing.text_utils import adjust_punctuation_after_deletion, clean_head_text, safe_re_sub
from npa_processor.processing.tree_utils import (
    adjust_highlights_for_paragraph_change,
    find_appendix_by_number,
    find_child_by_type_and_number,
    find_item_by_id,
)
from npa_processor.processing.ui_utils import (
    _add_new_element,
    _close_revision,
    _ensure_path,
    _fetch_source_html_for_change,
    _find_existing_element_flexible,
    _make_new_revision,
    build_new_body_preserving_child_refs,
    close_revision_date,
    is_highlights_empty,
    parse_add_new_field,
)


def _find_paragraph_by_content(paragraphs, search_text, log_callback=None):
    if not search_text or not paragraphs:
        return -1
    search_clean = ' '.join(search_text.split()).lower()
    for idx, para in enumerate(paragraphs):
        para_clean = ' '.join(BeautifulSoup(para, 'html.parser').get_text(separator=' ', strip=True).split()).lower()
        if search_clean in para_clean or para_clean in search_clean:
            return idx + 1
    return -1


def apply_grouped_changes(element, changes, valid_from, change_data, data, log_callback,
                          rebuild_ids, extra_options, source_item_id=None,
                          stop_event=None, manual_resolver=None, source_context_root=None):
    from npa_processor.processing.revision_builder import _merge_highlights_with_paragraph_prefix
    if stop_event and stop_event.is_set():
        if log_callback:
            log_callback("  apply_grouped_changes: остановка", 'warning')
        return False
    if log_callback:
        log_callback(f"Применение группы из {len(changes)} изменений к элементу {element.get('item_id')}", 'info')
    if any(c.get('type') == 'new_redaction' for c in changes):
        if not any('абзац' in c.get('structural_element', '').lower() for c in changes):
            ch = changes[0]
            rev_number = ch.get('revision_number')
            if '_quoted_html' in ch:
                source_html = ch['_quoted_html']
                if log_callback:
                    log_callback("  Используем ранее извлечённый HTML из _quoted_html", 'info')
            else:
                source_html = _fetch_source_html_for_change(ch, change_data, source_context_root, log_callback)
                if not source_html:
                    if log_callback:
                        log_callback(f"  Не удалось получить HTML из элемента-источника по revision_number {rev_number}", 'error')
                    return False
            range_str = ch.get('description', '').strip()
            final_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
            if not final_html and range_str:
                if log_callback:
                    log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' из HTML", 'error')
                return False
            if not final_html:
                final_html = source_html
            cleaned_html = clean_description_html(final_html)
            if log_callback:
                preview = cleaned_html[:30000] + ('...' if len(cleaned_html) > 30000 else '')
                log_callback(f"  Для new_redaction извлечён HTML: {preview}", 'source')
            modified_by_id_str = _resolve_modified_by_ids(
                rev_number, change_data, None, source_item_id, log_callback,
                structural_element=ch.get('structural_element', ''),
                manual_resolver=manual_resolver, stop_event=stop_event,
                context_root=source_context_root
            )
            if modified_by_id_str is None:
                modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
            is_table_child = element.get('_is_table_child', False)
            cleaned_html = clean_and_unwrap_html(cleaned_html, is_table_child=is_table_child)
            if element.get('item_type') in ('part', 'point', 'subpoint'):
                if not any(c.get('type') == 'new_redaction' for c in changes):
                    cleaned_html = remove_leading_number_from_html(
                        cleaned_html,
                        str(element.get('item_number', ''))
                    )
            element['_pending_new_redaction_html'] = cleaned_html
            element['_pending_modified_by_id'] = modified_by_id_str
            element['_pending_valid_from'] = valid_from.strftime('%d.%m.%Y')
            element['_pending_mod_type'] = 'new_redaction'
            element['_pending_highlights'] = None
            if element['item_id'] not in rebuild_ids:
                rebuild_ids.append(element['item_id'])
            if log_callback:
                log_callback("  new_redaction структурного элемента -> pending", 'result')
            return True
    paragraph_ops = []
    text_changes = []
    for ch in changes:
        ch_type = ch.get('type', '')
        if '_paragraph_num' in ch:
            paragraph_ops.append(ch)
            continue
        structural = ch.get('structural_element', '').lower()
        if 'абзац' in structural and ch_type in ('new_redaction', 'add', 'delete', 'change'):
            paragraph_ops.append(ch)
        else:
            text_changes.append(ch)
    revisions = element.setdefault('revisions', [])
    active_rev = None
    for rev in reversed(revisions):
        if rev.get('valid_to') is None:
            active_rev = rev
            break
    if not active_rev and revisions:
        active_rev = revisions[-1]
    if not active_rev:
        if log_callback:
            log_callback("  Нет активной ревизии у элемента", 'error')
        return False
    ai_paragraphs = []
    combined_highlights = None
    if text_changes:
        current_html = get_full_element_html(element, include_header=False)
        if not current_html.strip():
            if log_callback:
                log_callback(f"  Не удалось получить HTML-содержимое элемента {element.get('item_id')}. Изменения типа 'change' невозможны.", 'error')
            return False
        for ch in text_changes:
            desc = ch.get('description', '')
            structural = ch.get('structural_element', '')
            para_num = None
            if 'абзац' in structural.lower():
                para_num = _extract_paragraph_order(structural)
            if para_num is not None:
                desc = f"абзац {para_num}: {desc}"
            if log_callback:
                log_callback(f"  Отправка запроса к ИИ для изменения: {desc[:80]}...", 'info')
            answer = get_stage4_answer(f"{element.get('item_id')}_content", log_callback)
            if not answer:
                if log_callback:
                    log_callback("  Не удалось получить ответ от ИИ", 'error')
                return False
            answer_html, ai_highlights = parse_ai_response_for_prompt4(answer, desc, log_callback)
            if not answer_html:
                if log_callback:
                    log_callback("  Не удалось извлечь HTML из ответа ИИ", 'error')
                return False
            answer_html = safe_re_sub(r'(?i)^\s*<target_html>\s*', '', answer_html)
            answer_html = safe_re_sub(r'(?i)\s*</target_html>\s*$', '', answer_html)
            answer_html = safe_re_sub(r'^\s*<p[^>]*>\s*<strong>[^<]*</strong>\s*</p>\s*', '', answer_html, flags=re.DOTALL)
            if element.get('item_type') in ('part', 'point', 'subpoint'):
                answer_html = remove_leading_number_from_html(answer_html, str(element.get('item_number', '')))

            if element.get('_is_table_child', False) or element.get('item_type') == 'structured_table':
                old_html_for_diff = get_full_element_html(element, include_header=False)
                corrected = _correct_table_highlights(old_html_for_diff, answer_html, ai_highlights, log_callback)
                if corrected:
                    ai_highlights = corrected

            if ai_highlights:
                replacement_pairs = _extract_replacement_pairs(desc)
                if replacement_pairs and not _verify_ai_highlights_for_replacements(ai_highlights, replacement_pairs):
                    if log_callback:
                        log_callback("  Подсветка ИИ не соответствует замене в описании, будет использован программный дифф", 'warning')
                    ai_highlights = None

            current_html = answer_html
            if ai_highlights:
                combined_highlights = _merge_highlights_with_paragraph_prefix(combined_highlights, ai_highlights, 1)
        ai_paragraphs = split_html_to_paragraphs(current_html)
        if not ai_paragraphs:
            ai_paragraphs = [current_html] if current_html.strip() else []
        if log_callback:
            log_callback("  Текстовые изменения ИИ применены", 'result')
        if is_highlights_empty(combined_highlights) and text_changes:
            old_html_for_highlights = get_full_element_html(element, include_header=False)
            combined_desc = " ; ".join(ch.get('description', '') for ch in text_changes)
            computed = compute_highlights_from_html_diff(old_html_for_highlights, current_html, log_callback, change_description=combined_desc)
            if computed:
                combined_highlights = _merge_highlights_with_paragraph_prefix(combined_highlights, computed, 1)
    else:
        current_html = get_full_element_html(element, include_header=False)
        if not current_html.strip():
            if log_callback:
                log_callback(f"  Не удалось получить HTML-содержимое элемента {element.get('item_id')} для базовой ревизии.", 'error')
            return False
        current_html = strip_number_from_element_html(current_html, str(element.get('item_number', '')), element.get('item_type', ''))
        ai_paragraphs = split_html_to_paragraphs(current_html)
        if not ai_paragraphs:
            ai_paragraphs = [current_html] if current_html.strip() else []
    pending_paragraph_ops = []
    for op in paragraph_ops:
        structural = op.get('structural_element', '')
        ch_type = op.get('type', '')
        para_num = op.get('_paragraph_num')
        if para_num is None:
            para_num = _extract_paragraph_order(structural)
        if para_num is None:
            desc_text = op.get('description', '')
            para_match = re.search(r'абзац\s+(\d+)', desc_text, re.IGNORECASE)
            if para_match:
                para_num = int(para_match.group(1))
        if para_num is None:
            if log_callback:
                log_callback(f"  Не удалось извлечь номер абзаца из '{structural}'", 'error')
            continue
        if ch_type == 'delete':
            if 1 <= para_num <= len(ai_paragraphs):
                text_before = ai_paragraphs[para_num - 1]
                del ai_paragraphs[para_num - 1]
                combined_highlights = adjust_highlights_for_paragraph_change(
                    combined_highlights, 'delete', para_num, text_before=text_before
                )
                if log_callback:
                    log_callback(f"  Абзац {para_num} удалён", 'result')
            else:
                desc_text = op.get('description', '')
                content_idx = _find_paragraph_by_content(ai_paragraphs, desc_text, log_callback)
                if content_idx > 0:
                    text_before = ai_paragraphs[content_idx - 1]
                    del ai_paragraphs[content_idx - 1]
                    combined_highlights = adjust_highlights_for_paragraph_change(
                        combined_highlights, 'delete', content_idx, text_before=text_before
                    )
                    if log_callback:
                        log_callback(f"  Абзац {para_num} не найден по индексу, удалён по содержимому (позиция {content_idx})", 'result')
                else:
                    if log_callback:
                        log_callback(f"  Абзац {para_num} не найден для удаления, пропускаем", 'warning')
        else:
            pending_paragraph_ops.append({
                'type': ch_type,
                'target_idx': para_num,
                'op': op
            })
    for op in pending_paragraph_ops:
        op_type = op.get('type')
        target_idx = op.get('target_idx')
        original_op = op.get('op')
        if op_type == 'new_redaction':
            if '_quoted_html' in original_op:
                source_html = original_op['_quoted_html']
            else:
                source_html = _fetch_source_html_for_change(original_op, change_data, source_context_root, log_callback)
                if not source_html:
                    if log_callback:
                        log_callback(f"  Не удалось получить HTML для замены абзаца {target_idx} из источника", 'error')
                    return False
            range_str = original_op.get('description', '').strip()
            new_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
            if not new_html and range_str:
                if log_callback:
                    log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для абзаца {target_idx}", 'error')
                return False
            if not new_html:
                new_html = source_html
            new_html = clean_description_html(new_html)
            if 1 <= target_idx <= len(ai_paragraphs):
                old_html = ai_paragraphs[target_idx - 1]
                ai_paragraphs[target_idx - 1] = new_html
                combined_highlights = adjust_highlights_for_paragraph_change(
                    combined_highlights, 'new_redaction', target_idx,
                    text_before=old_html, text_after=new_html,
                    item_number=element.get('item_number'), item_type=element.get('item_type')
                )
                if log_callback:
                    log_callback(f"  Абзац {target_idx} заменён", 'result')
            else:
                insert_idx = target_idx - 1
                if insert_idx < 0:
                    insert_idx = 0
                if insert_idx > len(ai_paragraphs):
                    insert_idx = len(ai_paragraphs)
                ai_paragraphs.insert(insert_idx, new_html)
                combined_highlights = adjust_highlights_for_paragraph_change(
                    combined_highlights, 'add', insert_idx + 1,
                    text_after=new_html,
                    item_number=element.get('item_number'), item_type=element.get('item_type')
                )
                if log_callback:
                    log_callback(f"  Абзац {target_idx} вставлен", 'result')
        elif op_type == 'change':
            if 1 <= target_idx <= len(ai_paragraphs):
                old_html = ai_paragraphs[target_idx - 1]
                if log_callback:
                    log_callback(f"  Отправка запроса к ИИ для изменения абзаца {target_idx}...", 'info')
                answer = get_stage4_answer(f"{element.get('item_id')}_para_{target_idx}", log_callback)
                if answer:
                    new_html, ai_highlights = parse_ai_response_for_prompt4(answer, log_callback)
                    if new_html:
                        ai_paragraphs[target_idx - 1] = new_html
                        if ai_highlights:
                            combined_highlights = _merge_highlights_with_paragraph_prefix(combined_highlights, ai_highlights, target_idx)
                        else:
                            computed = compute_highlights_from_html_diff(old_html, new_html, log_callback)
                            if computed:
                                combined_highlights = _merge_highlights_with_paragraph_prefix(combined_highlights, computed, target_idx)
                        if log_callback:
                            log_callback(f"  Абзац {target_idx} изменён через ИИ", 'result')
                    else:
                        if log_callback:
                            log_callback(f"  Не удалось извлечь HTML для абзаца {target_idx}", 'error')
                else:
                    if log_callback:
                        log_callback(f"  Не удалось получить ответ ИИ для абзаца {target_idx}", 'error')
            else:
                desc_text = original_op.get('description', '')
                content_idx = _find_paragraph_by_content(ai_paragraphs, desc_text, log_callback)
                if content_idx > 0:
                    old_html = ai_paragraphs[content_idx - 1]
                    if log_callback:
                        log_callback(f"  Абзац {target_idx} не найден по индексу, изменяем по содержимому (позиция {content_idx})...", 'info')
                    answer = get_stage4_answer(f"{element.get('item_id')}_content", log_callback)
                if answer:
                    new_html, ai_highlights = parse_ai_response_for_prompt4(answer, log_callback)
                    if new_html:
                        ai_paragraphs[target_idx - 1] = new_html
                        if ai_highlights:
                            replacement_pairs = _extract_replacement_pairs(original_op.get('description', ''))
                            if replacement_pairs and not _verify_ai_highlights_for_replacements(ai_highlights, replacement_pairs):
                                if log_callback:
                                    log_callback(f"  Подсветка ИИ для абзаца {content_idx} не соответствует замене, будет использован программный дифф", 'warning')
                                ai_highlights = None
                        if ai_highlights:
                            combined_highlights = _merge_highlights_with_paragraph_prefix(combined_highlights, ai_highlights, content_idx)
                        else:
                            computed = compute_highlights_from_html_diff(old_html, new_html, log_callback, change_description=original_op.get('description', ''))
                            if computed:
                                combined_highlights = _merge_highlights_with_paragraph_prefix(combined_highlights, computed, content_idx)
                        if log_callback:
                            log_callback(f"  Абзац {content_idx} изменён через ИИ (по содержимому)", 'result')
                    else:
                        if log_callback:
                            log_callback(f"  Не удалось извлечь HTML для абзаца {content_idx}", 'error')
                else:
                    if log_callback:
                        log_callback(f"  Не удалось получить ответ ИИ для абзаца {content_idx}", 'error')
        elif op_type == 'add':
            if '_quoted_html' in original_op:
                source_html = original_op['_quoted_html']
            else:
                source_html = _fetch_source_html_for_change(original_op, change_data, source_context_root, log_callback)
                if not source_html:
                    if log_callback:
                        log_callback(f"  Не удалось получить HTML для добавления абзаца {target_idx} из источника", 'error')
                    return False
            range_str = original_op.get('description', '').strip()
            new_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
            if not new_html and range_str:
                if log_callback:
                    log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для добавления абзаца {target_idx}", 'error')
                return False
            if not new_html:
                new_html = source_html
            new_html = clean_description_html(new_html)
            insert_idx = target_idx - 1
            if insert_idx < 0:
                insert_idx = 0
            if insert_idx > len(ai_paragraphs):
                insert_idx = len(ai_paragraphs)
            ai_paragraphs.insert(insert_idx, new_html)
            combined_highlights = adjust_highlights_for_paragraph_change(
                combined_highlights, 'add', insert_idx + 1,
                text_after=new_html,
                item_number=element.get('item_number'), item_type=element.get('item_type')
            )
            if log_callback:
                log_callback(f"  Абзац {target_idx} добавлен", 'result')
    final_html = '\n'.join(ai_paragraphs)
    final_html = strip_number_from_element_html(final_html, str(element.get('item_number', '')), element.get('item_type'))
    if element.get('_is_table_child', False) and not re.search(r'<table|<tr|<td|<th', final_html, re.IGNORECASE):
        log_callback(
            f"  Результат обработки ИИ для табличного элемента {element.get('item_id')} "
            f"не содержит табличной разметки. Изменение не будет применено.",
            'error'
        )
        return False
    modified_by_id_str = _resolve_modified_by_ids(
        changes[0].get('revision_number'), change_data, None, source_item_id, log_callback,
        structural_element=changes[0].get('structural_element', ''),
        manual_resolver=manual_resolver, stop_event=stop_event,
        context_root=source_context_root
    )
    if modified_by_id_str is None:
        modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
        if log_callback:
            log_callback(f"  Использован ID изменяющего закона: {modified_by_id_str}", 'info')
    is_table_child = element.get('_is_table_child', False)
    final_html = clean_and_unwrap_html(final_html.strip(), is_table_child=is_table_child)
    is_number_change = False
    for ch in changes:
        structural = ch.get('structural_element', '').lower()
        if 'раздел' in structural or 'глава' in structural or 'статья' in structural:
            is_number_change = True
            break
    if is_number_change and element.get('_is_table_child', False):
        element['_pending_mod_type'] = 'change'
    else:
        element['_pending_mod_type'] = 'change'
    element['_pending_new_redaction_html'] = final_html
    element['_pending_modified_by_id'] = modified_by_id_str
    element['_pending_valid_from'] = valid_from.strftime('%d.%m.%Y')
    element['_pending_highlights'] = combined_highlights
    if element['item_id'] not in rebuild_ids:
        rebuild_ids.append(element['item_id'])
    if log_callback:
        log_callback("  Группа изменений применена: pending для перестройки", 'result')
    return True

def apply_change(change, data, change_data, law_ref, general_valid_from, log_callback,
                 source_item_id=None, rebuild_ids=None,
                 doc_type='law', extra_options=None, stop_event=None, manual_resolver=None,
                 source_context_root=None, ambiguous_callback=None):
    if rebuild_ids is None:
        rebuild_ids = []
    if '_resolved_item_id' in change:
        resolved_target_id = change['_resolved_item_id']
        if resolved_target_id == '__наименование__':
            return _apply_change_to_head(change, data, change_data, general_valid_from, change.get('revision_number'),
                                         None, source_item_id, log_callback, extra_options, stop_event,
                                         manual_resolver, source_context_root)
        elif resolved_target_id == '__преамбула__':
            return _apply_change_to_preamble(change, data, change_data, general_valid_from, change.get('revision_number'),
                                              None, source_item_id, log_callback, extra_options, stop_event,
                                              manual_resolver, source_context_root, rebuild_ids)
        elif resolved_target_id is None:
            structural = change.get('structural_element', '').strip()
            ch_type = change.get('type', '').strip()
            if ch_type == 'add':
                if 'new' in change and change['new']:
                    ru_type, child_num = parse_add_new_field(change['new'])
                    if not ru_type or not child_num:
                        log_callback(f"  Не удалось разобрать new: {change.get('new')}", 'error')
                        return False
                    sys_type = None
                    for eng, rus in TYPE_TO_RUSSIAN.items():
                        if rus.lower() == ru_type:
                            sys_type = eng
                            break
                    if not sys_type:
                        log_callback(f"  Неизвестный тип: {ru_type}", 'error')
                        return False
                    if '_quoted_html' in change:
                        source_html = change['_quoted_html']
                    else:
                        source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
                        if not source_html:
                            log_callback("  Не удалось получить HTML для add", 'error')
                            return False
                    range_str = change.get('description', '').strip()
                    cleaned_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
                    if not cleaned_html and range_str:
                        log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для add", 'error')
                        return False
                    if not cleaned_html:
                        cleaned_html = source_html
                    modified_by_id_str = _resolve_modified_by_ids(change.get('revision_number'), change_data, None, source_item_id, log_callback, structural_element=structural, manual_resolver=manual_resolver, stop_event=stop_event, context_root=source_context_root)
                    if modified_by_id_str is None:
                        modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
                    valid_from_date = general_valid_from
                    valid_from_str = change.get('valid_from')
                    if valid_from_str:
                        try:
                            valid_from_date = datetime.strptime(valid_from_str, '%d.%m.%Y').date()
                        except ValueError:
                            valid_from_date = general_valid_from
                    tokens = parse_structural_tokens(structural)
                    parent_element = None
                    if tokens:
                        parent_element = _ensure_path(data, tokens, valid_from_date, modified_by_id_str, log_callback, None, ambiguous_callback)
                    if parent_element:
                        new_id = _add_new_element(parent_element, sys_type, child_num, cleaned_html, modified_by_id_str, valid_from_date, data, log_callback, rebuild_ids, ambiguous_callback)
                    else:
                        new_id = _add_new_element(None, sys_type, child_num, cleaned_html, modified_by_id_str, valid_from_date, data, log_callback, rebuild_ids, ambiguous_callback, level_hint=2)
                    return new_id is not None
            tokens = parse_structural_tokens(structural)
            if not tokens:
                log_callback(f"  Не удалось разобрать путь для add: {structural}", 'error')
                return False
            modified_by_id_str = _resolve_modified_by_ids(change.get('revision_number'), change_data, None, source_item_id, log_callback, structural_element=structural, manual_resolver=manual_resolver, stop_event=stop_event, context_root=source_context_root)
            if modified_by_id_str is None:
                modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
            valid_from_date = general_valid_from
            valid_from_str = change.get('valid_from')
            if valid_from_str:
                try:
                    valid_from_date = datetime.strptime(valid_from_str, '%d.%m.%Y').date()
                except ValueError:
                    valid_from_date = general_valid_from
            if '_quoted_html' in change:
                source_html = change['_quoted_html']
            else:
                source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
                if not source_html:
                    log_callback("  Не удалось получить HTML для add", 'error')
                    return False
            range_str = change.get('description', '').strip()
            cleaned_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
            if not cleaned_html and range_str:
                log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для add", 'error')
                return False
            if not cleaned_html:
                cleaned_html = source_html
            if len(tokens) == 1:
                last_type, last_num = tokens[-1]
                new_id = _add_new_element(None, last_type, last_num, cleaned_html, modified_by_id_str, valid_from_date, data, log_callback, rebuild_ids, ambiguous_callback, level_hint=2)
                return new_id is not None
            parent_element = _ensure_path(data, tokens[:-1], valid_from_date, modified_by_id_str, log_callback, None, ambiguous_callback)
            if not parent_element:
                level_hint = len(tokens)
                log_callback(f"  Не удалось создать родительский путь для add, элемент будет добавлен на корневой уровень с level_hint={level_hint}", 'warning')
                last_type, last_num = tokens[-1]
                new_id = _add_new_element(None, last_type, last_num, cleaned_html, modified_by_id_str, valid_from_date, data, log_callback, rebuild_ids, ambiguous_callback, level_hint=level_hint)
                return new_id is not None
            last_type, last_num = tokens[-1]
            new_id = _add_new_element(parent_element, last_type, last_num, cleaned_html, modified_by_id_str, valid_from_date, data, log_callback, rebuild_ids, ambiguous_callback)
            return new_id is not None
        else:
            target_element = find_item_by_id(data, resolved_target_id)
            if not target_element:
                log_callback(f"Элемент {resolved_target_id} не найден в данных", 'error')
                return False
            ch_type = change.get('type', '').strip()
            structural = change.get('structural_element', '').strip()
            if ch_type == 'new_redaction' and '_paragraph_num' not in change:
                tokens = parse_structural_tokens(structural)
                if tokens:
                    last_type, last_num = tokens[-1]
                    child = find_child_by_type_and_number(target_element, last_type, last_num, ambiguous_callback)
                    if child:
                        log_callback(f"  Для new_redaction найден дочерний элемент {last_type} {last_num} внутри {target_element.get('item_id')}", 'info')
                        target_element = child
                    else:
                        log_callback(f"  Для new_redaction не найден дочерний элемент {last_type} {last_num} внутри {target_element.get('item_id')}, применяем к родителю", 'warning')
            description = change.get('description', '')
            rev_number = change.get('revision_number', None)
            valid_from_str = change.get('valid_from', None)
            if valid_from_str:
                try:
                    valid_from = datetime.strptime(valid_from_str, '%d.%m.%Y').date()
                except ValueError:
                    valid_from = general_valid_from
            else:
                valid_from = general_valid_from
            modified_by_id_str = _resolve_modified_by_ids(rev_number, change_data, None, source_item_id, log_callback, structural_element=structural, manual_resolver=manual_resolver, stop_event=stop_event, context_root=source_context_root)
            if not modified_by_id_str:
                modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
            structural_lower_check = structural.lower()
            if structural_lower_check.startswith('наименование ') or structural_lower_check.endswith(' наименование'):
                source_element_local = find_item_by_id(change_data, source_item_id) if source_item_id else None
                return _apply_change_to_element_head(change, data, change_data, valid_from, rev_number,
                                                          source_element_local, source_item_id, log_callback,
                                                          extra_options, stop_event, manual_resolver,
                                                          source_context_root, rebuild_ids)
            return _apply_change_to_element_content(target_element, ch_type, description, valid_from, modified_by_id_str, extra_options, stop_event, log_callback, rebuild_ids, structural, source_context_root, change_data, data, None, source_item_id, rev_number, change, manual_resolver)
    structural = change.get('structural_element', '').strip()
    ch_type = change.get('type', '').strip()
    description = change.get('description', '')
    rev_number = change.get('revision_number', None)
    valid_from_str = change.get('valid_from', None)
    if valid_from_str:
        try:
            valid_from = datetime.strptime(valid_from_str, '%d.%m.%Y').date()
        except ValueError:
            valid_from = general_valid_from
    else:
        valid_from = general_valid_from
    if not structural or not ch_type:
        log_callback("  Некорректное изменение", 'error')
        return False
    log_callback(f"  Тип: {ch_type} | Элемент: {structural}", 'info')
    source_element = None
    if source_item_id:
        source_element = find_item_by_id(change_data, source_item_id)
    structural_lower = structural.lower()
    if structural_lower.endswith(' префикс'):
        return _apply_change_to_appendix_prefix(change, data, change_data, valid_from, rev_number,
                                                 source_element, source_item_id, log_callback,
                                                 extra_options, stop_event, manual_resolver,
                                                 source_context_root, rebuild_ids)
    if structural_lower == "наименование":
        return _apply_change_to_head(change, data, change_data, valid_from, rev_number, source_element, source_item_id, log_callback, extra_options, stop_event, manual_resolver, source_context_root)
    if structural_lower.endswith(' наименование') and structural_lower != 'наименование':
        element_part = structural[:-len(' наименование')].strip()
        change_copy = change.copy()
        change_copy['structural_element'] = f"наименование {element_part}"
        return _apply_change_to_element_head(change_copy, data, change_data, valid_from, rev_number, source_element, source_item_id, log_callback, extra_options, stop_event, manual_resolver, source_context_root, rebuild_ids)
    if structural_lower.startswith('наименование '):
        return _apply_change_to_element_head(change, data, change_data, valid_from, rev_number, source_element, source_item_id, log_callback, extra_options, stop_event, manual_resolver, source_context_root, rebuild_ids)
    if structural_lower == "преамбула":
        return _apply_change_to_preamble(change, data, change_data, valid_from, rev_number, source_element, source_item_id, log_callback, extra_options, stop_event, manual_resolver, source_context_root, rebuild_ids)
    if ch_type == 'add':
        if 'new' in change and change['new']:
            ru_type, child_num = parse_add_new_field(change['new'])
            if not ru_type or not child_num:
                log_callback(f"  Не удалось разобрать new: {change.get('new')}", 'error')
                return False
            sys_type = None
            for eng, rus in TYPE_TO_RUSSIAN.items():
                if rus.lower() == ru_type:
                    sys_type = eng
                    break
            if not sys_type:
                log_callback(f"  Неизвестный тип: {ru_type}", 'error')
                return False
            if structural.lower() == 'нпа':
                parent_element = None
            else:
                parent_element = _find_existing_element_flexible(data, structural, log_callback, ambiguous_callback)
                if not parent_element:
                    log_callback(f"  Не найден родительский элемент для добавления: {structural}", 'error')
                    return False
            if '_quoted_html' in change:
                source_html = change['_quoted_html']
            else:
                source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
                if not source_html:
                    log_callback("  Не удалось получить HTML для add", 'error')
                    return False
            range_str = change.get('description', '').strip()
            cleaned_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
            if not cleaned_html and range_str:
                log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для add", 'error')
                return False
            if not cleaned_html:
                cleaned_html = source_html
            modified_by_id_str = _resolve_modified_by_ids(rev_number, change_data, source_element, source_item_id, log_callback, structural_element=structural, manual_resolver=manual_resolver, stop_event=stop_event, context_root=source_context_root)
            if modified_by_id_str is None:
                modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
            new_id = _add_new_element(parent_element, sys_type, child_num, cleaned_html, modified_by_id_str, valid_from, data, log_callback, rebuild_ids, ambiguous_callback, level_hint=2)
            return new_id is not None
        else:
            tokens = parse_structural_tokens(structural)
            if not tokens:
                log_callback(f"  Не удалось разобрать путь для add: {structural}", 'error')
                return False
            modified_by_id_str = _resolve_modified_by_ids(rev_number, change_data, source_element, source_item_id, log_callback, structural_element=structural, manual_resolver=manual_resolver, stop_event=stop_event, context_root=source_context_root)
            if modified_by_id_str is None:
                modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
            if '_quoted_html' in change:
                source_html = change['_quoted_html']
            else:
                source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
                if not source_html:
                    log_callback("  Не удалось получить HTML для add", 'error')
                    return False
            range_str = change.get('description', '').strip()
            cleaned_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
            if not cleaned_html and range_str:
                log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для add", 'error')
                return False
            if not cleaned_html:
                cleaned_html = source_html
            if len(tokens) == 1:
                last_type, last_num = tokens[-1]
                new_id = _add_new_element(None, last_type, last_num, cleaned_html, modified_by_id_str, valid_from, data, log_callback, rebuild_ids, ambiguous_callback, level_hint=2)
                return new_id is not None
            parent_element = _ensure_path(data, tokens[:-1], valid_from, modified_by_id_str, log_callback, None, ambiguous_callback)
            if not parent_element:
                level_hint = len(tokens)
                log_callback(f"  Не удалось создать родительский путь для add, элемент будет добавлен на корневой уровень с level_hint={level_hint}", 'warning')
                last_type, last_num = tokens[-1]
                new_id = _add_new_element(None, last_type, last_num, cleaned_html, modified_by_id_str, valid_from, data, log_callback, rebuild_ids, ambiguous_callback, level_hint=level_hint)
                return new_id is not None
            last_type, last_num = tokens[-1]
            new_id = _add_new_element(parent_element, last_type, last_num, cleaned_html, modified_by_id_str, valid_from, data, log_callback, rebuild_ids, ambiguous_callback)
            return new_id is not None
    target_element = _find_existing_element_flexible(data, structural, log_callback, ambiguous_callback)
    if target_element is None:
        log_callback(f"  Не найден или неоднозначен элемент для изменения: {structural}. Изменение пропущено.", 'warning')
        return False
    modified_by_id_str = _resolve_modified_by_ids(rev_number, change_data, source_element, source_item_id, log_callback, structural_element=structural, manual_resolver=manual_resolver, stop_event=stop_event, context_root=source_context_root)
    if not modified_by_id_str:
        modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
    return _apply_change_to_element_content(target_element, ch_type, description, valid_from, modified_by_id_str, extra_options, stop_event, log_callback, rebuild_ids, structural, source_context_root, change_data, data, source_element, source_item_id, rev_number, change, manual_resolver)

def _apply_change_to_appendix_prefix(change, data, change_data, valid_from, rev_number,
                                      source_element, source_item_id, log_callback,
                                      extra_options, stop_event, manual_resolver,
                                      source_context_root, rebuild_ids):
    structural = change.get('structural_element', '')
    ch_type = change.get('type', '')
    description = change.get('description', '')
    highlights = change.get('highlights', None)
    app_match = re.search(r'приложение\s+(\d+(?:\.\d+)?)', structural.lower())
    if app_match:
        app_number = app_match.group(1)
        app_element = find_appendix_by_number(data, app_number)
    else:
        app_element = _find_existing_element_flexible(data, 'приложение', log_callback)
    if not app_element:
        log_callback(f"  Приложение для изменения префикса не найдено: {structural}", 'error')
        return False
    if app_element.get('item_type') != 'appendix':
        log_callback(f"  Элемент {app_element.get('item_id')} не является приложением", 'error')
        return False
    prefix_revs = app_element.setdefault('item_prefix_revisions', [])
    active_idx = -1
    for i, rev in enumerate(prefix_revs):
        if rev.get('valid_to') is None:
            active_idx = i
            break
    if active_idx == -1 and prefix_revs:
        active_idx = len(prefix_revs) - 1
    current_prefix = prefix_revs[active_idx].get('prefix_text', '') if active_idx >= 0 else ''
    new_prefix = None
    if ch_type == 'new_redaction':
        if '_quoted_html' in change:
            source_html = change['_quoted_html']
        else:
            source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
            if not source_html:
                log_callback("  Не удалось получить HTML из элемента-источника", 'error')
                return False
        range_str = change.get('description', '').strip()
        new_prefix = extract_paragraphs_by_indices(source_html, range_str, log_callback)
        if not new_prefix and range_str:
            log_callback(f"  Не удалось извлечь префикс по диапазону '{range_str}'", 'error')
            return False
        if not new_prefix:
            new_prefix = source_html
        if log_callback:
            log_callback(f"  Префикс извлечён из кавычек: '{new_prefix}'", 'source')
    elif ch_type == 'change':
        answer = get_stage4_answer(f"prefix_{app_element.get('item_id')}", log_callback)
        if answer:
            answer_html, _ = parse_ai_response_for_prompt4(answer, log_callback)
            match = re.search(r'<p>(.*?)</p>', answer_html, re.DOTALL)
            new_prefix = match.group(1).strip() if match else answer_html.strip()
    elif ch_type == 'delete':
        new_prefix = None
    elif ch_type == 'add':
        new_prefix = description.strip() if description else ''
    if new_prefix == current_prefix:
        log_callback(f"  Префикс приложения не изменился: '{current_prefix}'", 'info')
        return True
    valid_to_str = close_revision_date(valid_from)
    if active_idx >= 0:
        prefix_revs[active_idx]['valid_to'] = valid_to_str
    if ch_type == 'add' and not current_prefix:
        mod_type = 'add'
    elif ch_type == 'delete' and current_prefix:
        mod_type = 'delete'
    else:
        mod_type = 'change'
    modified_by_id_str = _resolve_modified_by_ids(
        rev_number, change_data, source_element, source_item_id, log_callback,
        structural_element=structural, manual_resolver=manual_resolver, stop_event=stop_event,
        context_root=source_context_root
    )
    if not modified_by_id_str:
        modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
    new_rev = {
        'prefix_text': new_prefix if new_prefix is not None else '',
        'mod_type': mod_type,
        'modified_by_id': modified_by_id_str
    }
    if mod_type == 'add' and new_prefix:
        new_rev['valid_from'] = valid_from.strftime('%d.%m.%Y')
    if highlights is not None and not is_highlights_empty(highlights):
        new_rev['highlights'] = highlights
    prefix_revs.append(new_rev)
    log_callback(f"  Префикс приложения обновлён: '{current_prefix}' -> '{new_prefix}'", 'result')
    return True


def _apply_change_to_head(change, data, change_data, valid_from, rev_number,
                          source_element, source_item_id, log_callback,
                          extra_options, stop_event, manual_resolver,
                          source_context_root):
    ch_type = change.get('type')
    highlights = change.get('highlights', None)
    head_rev = data.get('head_revision', [])
    if not head_rev:
        if log_callback:
            log_callback("  В JSON отсутствует head_revision", 'error')
        return False
    active_idx = -1
    for i, rev in enumerate(head_rev):
        if rev.get('valid_to') in (None, ''):
            active_idx = i
            break
    if active_idx == -1 and head_rev:
        active_idx = len(head_rev) - 1
    active = head_rev[active_idx]
    current_head = active.get('npa_head', '')
    if ch_type == 'change':
        if log_callback:
            log_callback(f"  Текущий заголовок: {current_head}", 'input')
        if log_callback:
            log_callback("  Запрос к ИИ для нового заголовка...", 'info')
        answer = get_stage4_answer("head", log_callback)
        if answer is None:
            if log_callback:
                log_callback("  Не удалось получить ответ от ИИ для заголовка", 'error')
            return False
        answer_html, highlights = parse_ai_response_for_prompt4(answer, log_callback)
        if not answer_html:
            if log_callback:
                log_callback("  Не удалось извлечь HTML из ответа ИИ", 'error')
            return False
        match = re.search(r'<p>(.*?)</p>', answer_html, re.DOTALL)
        new_head = match.group(1).strip() if match else answer_html.strip()
        if not new_head:
            if log_callback:
                log_callback("  Получен пустой заголовок", 'error')
            return False
        if log_callback:
            log_callback(f"  Новый заголовок: {new_head}", 'result')
    elif ch_type == 'new_redaction':
        if '_quoted_html' in change:
            source_html = change['_quoted_html']
        else:
            source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
            if not source_html:
                if log_callback:
                    log_callback(f"  Не удалось получить HTML из элемента-источника по revision_number {rev_number}", 'error')
                return False
        range_str = change.get('description', '').strip()
        new_head = extract_paragraphs_by_indices(source_html, range_str, log_callback)
        if not new_head and range_str:
            if log_callback:
                log_callback(f"  Не удалось извлечь заголовок по диапазону '{range_str}'", 'error')
            return False
        if not new_head:
            new_head = source_html
        new_head = safe_re_sub(r'<[^>]+>', ' ', new_head)
        new_head = new_head.replace('&laquo;', '«').replace('&raquo;', '»')
        new_head = new_head.replace('&nbsp;', ' ').replace('&amp;', '&')
        new_head = ' '.join(new_head.split())
        if log_callback:
            log_callback(f"  Заголовок извлечён из кавычек: {new_head}", 'source')
    else:
        if log_callback:
            log_callback(f"  Неизвестный тип для наименования: {ch_type}", 'warning')
        return False
    valid_to_str = close_revision_date(valid_from)
    modified_by_id_str = _resolve_modified_by_ids(
        rev_number, change_data, source_element, source_item_id, log_callback,
        structural_element=change.get('structural_element', ''), manual_resolver=manual_resolver, stop_event=stop_event,
        context_root=source_context_root)
    if modified_by_id_str is None:
        if log_callback:
            log_callback("  Не удалось определить modified_by_id для заголовка", 'error')
        return False
    _close_revision(head_rev[active_idx], valid_to_str)
    new_rev = {
        'npa_head': new_head,
        'mod_type': ch_type,
        'modified_by_id': modified_by_id_str
    }
    if highlights is not None and not is_highlights_empty(highlights):
        new_rev['highlights'] = highlights
    head_rev.append(new_rev)
    data['head_revision'] = head_rev
    if log_callback:
        log_callback(f"  Заголовок обновлён: {new_head}", 'result')
    return True

def _apply_change_to_element_head(change, data, change_data, valid_from, rev_number,
                                    source_element, source_item_id, log_callback,
                                    extra_options, stop_event, manual_resolver,
                                    source_context_root, rebuild_ids):
    structural = change.get('structural_element', '').strip()
    ch_type = change.get('type', '').strip()
    highlights = change.get('highlights', None)
    element_structural = structural[len('наименование '):].strip()
    resolved_id = change.get('_resolved_item_id')
    if resolved_id:
        target_element = find_item_by_id(data, resolved_id)
        if not target_element:
            log_callback(f"  Элемент с _resolved_item_id {resolved_id} не найден, выполняем поиск по structural", 'warning')
            target_element = _find_existing_element_flexible(data, element_structural, log_callback)
    else:
        target_element = _find_existing_element_flexible(data, element_structural, log_callback)
    if not target_element:
        log_callback(f"  Не найден элемент для изменения наименования: {element_structural}", 'error')
        return False
    item_type_head = target_element.get('item_type', '')
    if item_type_head not in ('article', 'chapter', 'section', 'appendix'):
        log_callback(f"  Тип '{item_type_head}' не поддерживает поле наименования", 'warning')
        return False
    modified_by_id_str = _resolve_modified_by_ids(
        rev_number, change_data, source_element, source_item_id, log_callback,
        structural_element=structural, manual_resolver=manual_resolver, stop_event=stop_event,
        context_root=source_context_root)
    if modified_by_id_str is None:
        log_callback("  Не удалось определить modified_by_id для наименования элемента", 'error')
        return False
    head_revisions = target_element.setdefault('head_revisions', [])
    active_idx = -1
    for i, rev in enumerate(head_revisions):
        if rev.get('valid_to') is None:
            active_idx = i
            break
    if active_idx == -1 and head_revisions:
        active_idx = len(head_revisions) - 1
    valid_to_str = close_revision_date(valid_from)
    new_head = None
    if ch_type == 'new_redaction':
        if '_quoted_html' in change:
            source_html = change['_quoted_html']
        else:
            source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
            if not source_html:
                if log_callback:
                    log_callback(f"  Не удалось получить HTML из элемента-источника по revision_number {rev_number}", 'error')
                return False
        range_str = change.get('description', '').strip()
        new_head = extract_paragraphs_by_indices(source_html, range_str, log_callback)
        if not new_head and range_str:
            if log_callback:
                log_callback(f"  Не удалось извлечь заголовок по диапазону '{range_str}'", 'error')
            return False
        if not new_head:
            new_head = source_html
        if log_callback:
            log_callback(f"  Заголовок извлечён из кавычек: {new_head}", 'source')
    elif ch_type == 'change':
        current_head = get_current_head(target_element)
        log_callback(f"Текущее наименование: {current_head}", 'input')
        log_callback("  Запрос к ИИ для изменения наименования...", 'info')
        answer_head = get_stage4_answer(f"{target_element.get('item_id')}_head", log_callback)
        if answer_head is None:
            log_callback("  Не удалось получить ответ от ИИ для наименования", 'error')
            return False
        answer_html, highlights = parse_ai_response_for_prompt4(answer_head, log_callback)
        if not answer_html:
            log_callback("  Не удалось извлечь HTML из ответа ИИ", 'error')
            return False
        head_match = re.search(r'<p>(.*?)</p>', answer_html, re.DOTALL)
        new_head = head_match.group(1).strip() if head_match else safe_re_sub(r'<[^>]+>', '', answer_html).strip()
        if not new_head:
            log_callback("  Получено пустое наименование", 'error')
            return False
    else:
        log_callback(f"  Неподдерживаемый тип для наименования элемента: {ch_type}", 'warning')
        return False
    item_number = target_element.get('item_number', '')
    new_head = clean_head_text(new_head, item_type_head, str(item_number))
    if log_callback:
        log_callback(f"  Заголовок после очистки: '{new_head}'", 'info')
    if active_idx >= 0:
        head_revisions[active_idx]['valid_to'] = valid_to_str
    new_rev = {
        'head_text': new_head,
        'mod_type': ch_type,
        'modified_by_id': modified_by_id_str
    }
    if highlights is not None and not is_highlights_empty(highlights):
        new_rev['highlights'] = highlights
    head_revisions.append(new_rev)
    log_callback(f"  Наименование элемента обновлено: {new_head}", 'result')
    return True

def _apply_change_to_preamble(change, data, change_data, valid_from, rev_number,
                                source_element, source_item_id, log_callback,
                                extra_options, stop_event, manual_resolver,
                                source_context_root, rebuild_ids):
    from npa_processor.processing.revision_builder import extract_child_refs_from_revision
    ch_type = change.get('type', '').strip()
    highlights = change.get('highlights', None)
    def find_preamble_item(items):
        for item in items:
            if item.get('item_type') == 'preamble':
                return item
            if 'item_children' in item:
                found = find_preamble_item(item['item_children'])
                if found:
                    return found
        return None
    preamble_item = find_preamble_item(data.get('npa_items_revision', []))
    if not preamble_item:
        if log_callback:
            log_callback("  Элемент преамбулы не найден в структуре", 'error')
        return False
    element = preamble_item
    if 'revisions' not in element:
        element['revisions'] = [{'body': []}]
    revisions = element['revisions']
    active_idx = -1
    for i, rev in enumerate(revisions):
        if rev.get('valid_to') in (None, ''):
            active_idx = i
            break
    if active_idx == -1 and revisions:
        active_idx = len(revisions) - 1
    old_rev = revisions[active_idx] if active_idx >= 0 else None
    modified_by_id_str = _resolve_modified_by_ids(
        rev_number, change_data, source_element, source_item_id, log_callback,
        structural_element=change.get('structural_element', ''), manual_resolver=manual_resolver, stop_event=stop_event,
        context_root=source_context_root)
    if modified_by_id_str is None:
        if log_callback:
            log_callback("  Не удалось определить modified_by_id для преамбулы", 'error')
        return False
    valid_to_str = close_revision_date(valid_from)
    if ch_type == 'delete':
        if active_idx >= 0:
            revisions[active_idx]['valid_to'] = valid_to_str
            revisions[active_idx]['not_valid'] = modified_by_id_str
        if log_callback:
            log_callback("  Преамбула помечена как удалённая", 'result')
        return True
    elif ch_type == 'change':
        current_html = get_full_element_html(element, include_header=False)
        if log_callback:
            log_callback(f"  Текущий HTML преамбулы (длина {len(current_html)} символов)", 'input')
        if log_callback:
            log_callback("  Запрос к ИИ для изменения преамбулы...", 'info')
        answer = get_stage4_answer(f"{element.get('item_id')}_content", log_callback)
        if answer is None:
            if log_callback:
                log_callback("  Не удалось получить ответ от ИИ", 'error')
            return False
        answer_html, highlights = parse_ai_response_for_prompt4(answer, log_callback)
        if not answer_html:
            if log_callback:
                log_callback("  Не удалось извлечь HTML из ответа ИИ", 'error')
            return False
        answer_html = safe_re_sub(r'(?i)^\s*<target_html>\s*', '', answer_html)
        answer_html = safe_re_sub(r'(?i)\s*</target_html>\s*$', '', answer_html)
        answer_html = remove_leading_number_from_html(answer_html, element.get('item_number', ''))
        answer_html = safe_re_sub(r'^\s*<p[^>]*>\s*<strong>[^<]*</strong>\s*</p>\s*', '', answer_html, flags=re.DOTALL)
        new_body = build_new_body_preserving_child_refs(old_rev, answer_html)
        if active_idx >= 0:
            revisions[active_idx]['valid_to'] = valid_to_str
        new_revision = _make_new_revision(new_body, mod_type='change', modified_by_id=modified_by_id_str, highlights=highlights)
        revisions.append(new_revision)
        if log_callback:
            log_callback("  Получен новый HTML от ИИ для преамбулы", 'result')
        return True
    elif ch_type == 'new_redaction':
        if '_quoted_html' in change:
            source_html = change['_quoted_html']
        else:
            source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
            if not source_html:
                if log_callback:
                    log_callback(f"  Не удалось получить HTML из элемента-источника по revision_number {rev_number}", 'error')
                return False
        range_str = change.get('description', '').strip()
        final_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
        if not final_html and range_str:
            if log_callback:
                log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для преамбулы", 'error')
            return False
        if not final_html:
            final_html = source_html
        if log_callback:
            preview = final_html[:30000] + ('...' if len(final_html) > 30000 else '')
            log_callback(f"  Для преамбулы извлечён HTML из кавычек: {preview}", 'source')
        cleaned_html = remove_leading_number_from_html(final_html, element.get('item_number', ''))
        is_table_child = preamble_item.get('_is_table_child', False)
        cleaned_html = clean_and_unwrap_html(cleaned_html, is_table_child=is_table_child)
        new_body = [{'type': 'paragraph', 'html_text': cleaned_html, 'order': 1}] if cleaned_html else []
        old_child_refs = extract_child_refs_from_revision(old_rev) if old_rev else []
        if old_child_refs:
            for i, ref in enumerate(old_child_refs):
                new_ref = copy.deepcopy(ref)
                new_ref['order'] = len(new_body) + i + 1
                new_body.append(new_ref)
        if active_idx >= 0:
            revisions[active_idx]['valid_to'] = valid_to_str
        new_revision = _make_new_revision(new_body, mod_type='new_redaction', modified_by_id=modified_by_id_str, highlights=highlights)
        revisions.append(new_revision)
        if log_callback:
            log_callback("  Преамбула заменена новой редакцией (источник)", 'result')
        return True
    else:
        if log_callback:
            log_callback(f"  Неизвестный тип для преамбулы: {ch_type}", 'warning')
        return False

def _apply_change_to_element_content(element, ch_type, description, valid_from,
                                      modified_by_id_str, extra_options,
                                      stop_event, log_callback, rebuild_ids,
                                      structural, source_context_root, change_data, data,
                                      source_element, source_item_id, rev_number,
                                      change, manual_resolver=None):
    from npa_processor.processing.revision_builder import extract_child_refs_from_revision
    if 'revisions' not in element:
        element['revisions'] = [{'body': []}]
    revisions = element['revisions']
    active_idx = -1
    for i, rev in enumerate(revisions):
        if rev.get('valid_to') in (None, ''):
            active_idx = i
            break
    if active_idx == -1 and revisions:
        active_idx = len(revisions) - 1
    old_rev = revisions[active_idx] if active_idx >= 0 else None
    if active_idx >= 0:
        valid_to_str = close_revision_date(valid_from)
    if ch_type == 'delete':
        if modified_by_id_str is None:
            if log_callback:
                log_callback("  Не удалось определить modified_by_id для удаления", 'error')
            return False
        if active_idx >= 0:
            revisions[active_idx]['valid_to'] = valid_to_str
            revisions[active_idx]['not_valid'] = modified_by_id_str
        if log_callback:
            log_callback(f"  Элемент '{structural}' помечен как удалённый", 'result')
        def find_parent(data, target_id):
            def recurse(items, parent=None):
                for item in items:
                    if item.get('item_id') == target_id:
                        return parent
                    found = recurse(item.get('item_children', []), item)
                    if found:
                        return found
                return None
            return recurse(data.get('npa_items_revision', []))
        parent = find_parent(data, element.get('item_id'))
        adjust_punctuation_after_deletion(parent, element, log_callback)
        return True
    elif ch_type == 'add':
        if log_callback:
            log_callback("  Добавление структурного элемента обрабатывается в блоке add", 'warning')
        return False
    elif ch_type == 'change':
        if modified_by_id_str is None:
            if log_callback:
                log_callback("  Не удалось определить modified_by_id для изменения", 'error')
            return False
        has_children = bool(element.get('item_children'))
        if has_children:
            old_child_refs = extract_child_refs_from_revision(old_rev) if old_rev else []
            current_html = get_full_element_html(element, include_header=False)
            if log_callback:
                log_callback(f"  Текущий HTML элемента (длина {len(current_html)} символов)", 'input')
                if " ; " in description and not description.startswith("1. "):
                    parts = [p.strip() for p in description.split(" ; ")]
                    formatted_desc = "\n".join(f"{i+1}. {p}" for i, p in enumerate(parts))
                    if log_callback:
                        log_callback("  Преобразовано описание в нумерованный список", 'info')
                    description = formatted_desc
                if log_callback:
                    log_callback("  Запрос к ИИ для изменения элемента (с дочерними)...", 'info')
                answer = get_stage4_answer("preamble", log_callback)
            if answer is None:
                if log_callback:
                    log_callback("  Не удалось получить ответ от ИИ", 'error')
                return False
            answer_html, highlights = parse_ai_response_for_prompt4(answer, log_callback)
            if not answer_html:
                if log_callback:
                    log_callback("  Не удалось извлечь HTML из ответа ИИ", 'error')
                return False
            paragraphs = split_html_to_paragraphs(answer_html)
            if not paragraphs:
                paragraphs = [answer_html] if answer_html.strip() else []
            if paragraphs and element.get('item_type') in ('part', 'point', 'subpoint'):
                paragraphs[0] = remove_leading_number_from_html(paragraphs[0], str(element.get('item_number', '')))
            new_body = []
            for idx, para in enumerate(paragraphs, start=1):
                new_body.append({'type': 'paragraph', 'html_text': para, 'order': idx})
            if old_child_refs:
                last_paragraph_idx = -1
                for idx, block in enumerate(new_body):
                    if block.get('type') == 'paragraph':
                        last_paragraph_idx = idx
                insert_pos = last_paragraph_idx + 1 if last_paragraph_idx != -1 else len(new_body)
                for i, ref in enumerate(old_child_refs):
                    new_ref = copy.deepcopy(ref)
                    new_ref['order'] = insert_pos + i + 1
                    new_body.insert(insert_pos + i, new_ref)
                for idx, block in enumerate(new_body, start=1):
                    block['order'] = idx
            if active_idx >= 0:
                revisions[active_idx]['valid_to'] = valid_to_str
            if is_highlights_empty(highlights):
                old_html_for_highlights = get_full_element_html(element, include_header=False)
                computed = compute_highlights_from_html_diff(old_html_for_highlights, answer_html, log_callback, change_description=description)
                if computed:
                    highlights = computed
            new_rev = _make_new_revision(new_body, mod_type='change', modified_by_id=modified_by_id_str, highlights=highlights)
            revisions.append(new_rev)
            rebuild_ids.append(element['item_id'])
            if log_callback:
                log_callback("  Элемент обновлён через ИИ (сохранён HTML для перестройки)", 'result')
            return True
        else:
            is_table_child = element.get('_is_table_child', False)
            if is_table_child:
                current_html = get_full_element_html(element, include_header=False)
                if log_callback:
                    log_callback("  Элемент является дочерним для структурированной таблицы, сохраняем HTML как есть", 'info')
                new_html = description
                if not new_html:
                    if '_quoted_html' in change:
                        source_html = change['_quoted_html']
                    else:
                        source_html = _fetch_source_html_for_change(change, change_data, source_context_root, log_callback)
                        if source_html:
                            pass
                    range_str = change.get('description', '').strip()
                    new_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
                    if not new_html and range_str:
                        if log_callback:
                            log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для табличного элемента", 'error')
                        return False
                    if not new_html:
                        new_html = source_html
                if new_html:
                    new_html = clean_description_html(new_html)
                    if element.get('item_type') in ('part', 'point', 'subpoint'):
                        new_html = remove_leading_number_from_html(new_html, str(element.get('item_number', '')))
                    is_table_child = element.get('_is_table_child', False)
                    new_html = clean_and_unwrap_html(new_html, is_table_child=is_table_child)
                    new_body = [{'type': 'table_fragment', 'html_text': new_html, 'order': 1}]
                    old_child_refs = extract_child_refs_from_revision(old_rev) if old_rev else []
                    if old_child_refs:
                        for i, ref in enumerate(old_child_refs):
                            new_ref = copy.deepcopy(ref)
                            new_ref['order'] = len(new_body) + i + 1
                            new_body.append(new_ref)
                    if active_idx >= 0:
                        revisions[active_idx]['valid_to'] = valid_to_str
                    new_rev = _make_new_revision(new_body, mod_type='change', modified_by_id=modified_by_id_str, highlights=highlights)
                    revisions.append(new_rev)
                    rebuild_ids.append(element['item_id'])
                    if log_callback:
                        log_callback("  Элемент таблицы обновлён (сохранён фрагмент)", 'result')
                    return True
                else:
                    log_callback("  Не удалось получить HTML для табличного элемента", 'error')
                    return False
                current_html = get_full_element_html(element, include_header=False)
                if log_callback:
                    log_callback(f"  Текущий HTML элемента (длина {len(current_html)} символов)", 'input')
                if " ; " in description and not description.startswith("1. "):
                    parts = [p.strip() for p in description.split(" ; ")]
                    formatted_desc = "\n".join(f"{i+1}. {p}" for i, p in enumerate(parts))
                    if log_callback:
                        log_callback("  Преобразовано описание в нумерованный список", 'info')
                    description = formatted_desc
                if log_callback:
                    log_callback("  Запрос к ИИ (промпт 4)...", 'info')
                answer = get_stage4_answer(f"{element.get('item_id')}_content", log_callback)
                if answer is None:
                    if log_callback:
                        log_callback("  Не удалось получить ответ от ИИ", 'error')
                    return False
                answer_html, highlights = parse_ai_response_for_prompt4(answer, log_callback)
                if not answer_html:
                    if log_callback:
                        log_callback("  Не удалось извлечь HTML из ответа ИИ", 'error')
                    return False
                answer_html = safe_re_sub(r'(?i)^\s*<target_html>\s*', '', answer_html)
                answer_html = safe_re_sub(r'(?i)\s*</target_html>\s*$', '', answer_html)
                answer_html = safe_re_sub(r'^\s*<p[^>]*>\s*<strong>[^<]*</strong>\s*</p>\s*', '', answer_html, flags=re.DOTALL)
                if element.get('item_type') in ('part', 'point', 'subpoint'):
                    answer_html = remove_leading_number_from_html(answer_html, str(element.get('item_number', '')))
                is_table_child = element.get('_is_table_child', False)
                answer_html = clean_and_unwrap_html(answer_html, is_table_child=is_table_child)
                old_child_refs = extract_child_refs_from_revision(old_rev) if old_rev else []
                new_body = build_new_body_preserving_child_refs(old_rev, answer_html)
                if active_idx >= 0:
                    revisions[active_idx]['valid_to'] = valid_to_str
                if is_highlights_empty(highlights):
                    old_html_for_highlights = get_full_element_html(element, include_header=False)
                    computed = compute_highlights_from_html_diff(old_html_for_highlights, answer_html, log_callback, change_description=description)
                    if computed:
                        highlights = computed
                new_revision = _make_new_revision(new_body, mod_type='change', modified_by_id=modified_by_id_str, highlights=highlights)
                revisions.append(new_revision)
                rebuild_ids.append(element['item_id'])
                if log_callback:
                    log_callback(f"  Получен новый HTML от ИИ (длина {len(answer_html)} символов)", 'result')
                return True
    elif ch_type == 'new_redaction':
        if modified_by_id_str is None:
            if log_callback:
                log_callback("  Не удалось определить modified_by_id для замены", 'error')
            return False
        is_table_child = element.get('_is_table_child', False)
        if is_table_child:
            if '_quoted_html' in change:
                source_html = change['_quoted_html']
            else:
                source_html = None
                if rev_number and rev_number != 'null':
                    rev_list = rev_number if isinstance(rev_number, list) else [rev_number]
                    for rn in rev_list:
                        source_id = find_item_by_revision_number(change_data, rn, context_root=source_context_root)
                        if source_id:
                            source_elem = find_item_by_id(change_data, source_id)
                            if source_elem:
                                source_html = get_full_element_html(source_elem, include_header=False)
                                if source_html:
                                    if log_callback:
                                        preview = source_html[:30000] + ('...' if len(source_html) > 30000 else '')
                                        log_callback(f"  HTML для новой редакции взят из элемента-источника (ID {source_id}): {preview}", 'source')
                                    break
                else:
                    if source_context_root:
                        source_html = get_full_element_html(source_context_root, include_header=False)
                        if log_callback:
                            log_callback(f"  revision_number == null, берём HTML из target_element (ID {source_context_root.get('item_id')})", 'info')
                    else:
                        log_callback("  revision_number == null, но target_element не передан", 'error')
                        return False
                if not source_html:
                    if log_callback:
                        log_callback("  Не удалось получить HTML для новой редакции табличного элемента", 'error')
                    return False
            range_str = change.get('description', '').strip()
            cleaned_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
            if not cleaned_html and range_str:
                if log_callback:
                    log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для табличного элемента", 'error')
                return False
            if not cleaned_html:
                cleaned_html = source_html
            if not re.search(r'<table|<tr|<td|<th', cleaned_html, re.IGNORECASE):
                log_callback(
                    f"  Новая редакция для табличного элемента (ID {element.get('item_id')}) "
                    f"не содержит табличной разметки. Изменение не будет применено.",
                    'error'
                )
                return False
            if element.get('item_type') in ('part', 'point', 'subpoint'):
                cleaned_html = remove_leading_number_from_html(cleaned_html, str(element.get('item_number', '')))
            if active_idx >= 0:
                valid_to_str = close_revision_date(valid_from)
                _close_revision(revisions[active_idx], valid_to_str)
            is_table_child = element.get('_is_table_child', False)
            cleaned_html = clean_and_unwrap_html(cleaned_html, is_table_child=is_table_child)
            element['_pending_new_redaction_html'] = cleaned_html
            element['_pending_modified_by_id'] = modified_by_id_str
            element['_pending_valid_from'] = valid_from.strftime('%d.%m.%Y')
            element['_pending_mod_type'] = 'new_redaction'
            rebuild_ids.append(element['item_id'])
            if log_callback:
                log_callback(f"  Элемент таблицы '{structural}' заменён новой редакцией (сохранён фрагмент)", 'result')
            return True
        else:
            if '_quoted_html' in change:
                source_html = change['_quoted_html']
            else:
                source_html = None
                if rev_number and rev_number != 'null':
                    rev_list = rev_number if isinstance(rev_number, list) else [rev_number]
                    for rn in rev_list:
                        source_id = find_item_by_revision_number(change_data, rn, context_root=source_context_root)
                        if source_id:
                            source_elem = find_item_by_id(change_data, source_id)
                            if source_elem:
                                source_html = get_full_element_html(source_elem, include_header=False)
                                if source_html:
                                    if log_callback:
                                        preview = source_html[:30000] + ('...' if len(source_html) > 30000 else '')
                                        log_callback(f"  HTML для новой редакции взят из элемента-источника (ID {source_id}): {preview}", 'source')
                                    break
                else:
                    if source_context_root:
                        source_html = get_full_element_html(source_context_root, include_header=False)
                        if log_callback:
                            log_callback(f"  revision_number == null, берём HTML из target_element (ID {source_context_root.get('item_id')})", 'info')
                    else:
                        log_callback("  revision_number == null, но target_element не передан", 'error')
                        return False
                if not source_html:
                    if log_callback:
                        log_callback("  Не удалось получить HTML для новой редакции", 'error')
                    return False
            range_str = change.get('description', '').strip()
            cleaned_html = extract_paragraphs_by_indices(source_html, range_str, log_callback)
            if not cleaned_html and range_str:
                if log_callback:
                    log_callback(f"  Не удалось извлечь абзацы по диапазону '{range_str}' для новой редакции", 'error')
                return False
            if not cleaned_html:
                cleaned_html = source_html
            if element.get('item_type') in ('part', 'point', 'subpoint'):
                cleaned_html = remove_leading_number_from_html(cleaned_html, str(element.get('item_number', '')))
            if element.get('item_type') in ('article', 'chapter', 'section') and not re.search(r'<[^>]+>', cleaned_html):
                lines = [line.strip() for line in cleaned_html.split('\n') if line.strip()]
                html_parts = []
                for line in lines:
                    html_parts.append(f'<p>{line}</p>')
                cleaned_html = '\n'.join(html_parts)
                if log_callback:
                    log_callback(f"  Преобразованный HTML для new_redaction: {cleaned_html[:200]}...", 'info')
            if active_idx >= 0:
                valid_to_str = close_revision_date(valid_from)
                _close_revision(revisions[active_idx], valid_to_str)
            is_table_child = element.get('_is_table_child', False)
            cleaned_html = clean_and_unwrap_html(cleaned_html, is_table_child=is_table_child)
            element['_pending_new_redaction_html'] = cleaned_html
            element['_pending_modified_by_id'] = modified_by_id_str
            element['_pending_valid_from'] = valid_from.strftime('%d.%m.%Y')
            element['_pending_mod_type'] = 'new_redaction'
            rebuild_ids.append(element['item_id'])
            if log_callback:
                log_callback(f"  Элемент '{structural}' заменён новой редакцией (запрос на перестройку)", 'result')
            return True
    else:
        if log_callback:
            log_callback(f"  Неизвестный тип: {ch_type}", 'warning')
        return False

