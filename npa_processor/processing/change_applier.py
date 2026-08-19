"""Применение изменений к документу."""

import copy
import re
from datetime import datetime

from bs4 import BeautifulSoup

from npa_processor.constants import TYPE_TO_RUSSIAN
from npa_processor.processing.stage_answers import get_stage4_agent_answer
from npa_processor.processing.element_finder import (
    _extract_paragraph_order,
    _resolve_modified_by_ids,
    find_item_by_revision_number,
)

from npa_processor.processing.element_ops import (
    _add_new_element,
    _close_revision,
    _ensure_path,
    _fetch_source_html_for_change,
    _find_existing_element_flexible,
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


def apply_change(change, data, change_data, law_ref, general_valid_from, log_callback,
                 source_item_id=None, rebuild_ids=None,
                 doc_type='law', extra_options=None,
                 source_context_root=None, ambiguous_callback=None):
    if rebuild_ids is None:
        rebuild_ids = []
    if '_resolved_item_id' in change:
        resolved_target_id = change['_resolved_item_id']
        if resolved_target_id == '__наименование__':
            return _apply_change_to_head(change, data, change_data, general_valid_from, change.get('revision_number'),
                                         None, source_item_id, log_callback, extra_options, source_context_root)
        elif resolved_target_id == '__преамбула__':
            return _apply_change_to_preamble(change, data, change_data, general_valid_from, change.get('revision_number'),
                                              None, source_item_id, log_callback, extra_options, source_context_root, rebuild_ids)
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
                    modified_by_id_str = _resolve_modified_by_ids(change.get('revision_number'), change_data, None, source_item_id, log_callback, structural_element=structural,  context_root=source_context_root)
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
            modified_by_id_str = _resolve_modified_by_ids(change.get('revision_number'), change_data, None, source_item_id, log_callback, structural_element=structural,  context_root=source_context_root)
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
            modified_by_id_str = _resolve_modified_by_ids(rev_number, change_data, None, source_item_id, log_callback, structural_element=structural,  context_root=source_context_root)
            if not modified_by_id_str:
                modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
            structural_lower_check = structural.lower()
            if structural_lower_check.startswith('наименование ') or structural_lower_check.endswith(' наименование'):
                source_element_local = find_item_by_id(change_data, source_item_id) if source_item_id else None
                return _apply_change_to_element_head(change, data, change_data, valid_from, rev_number,
                                                          source_element_local, source_item_id, log_callback,
                                                          extra_options,
                                                          source_context_root, rebuild_ids)
            return _apply_change_to_element_content(target_element, ch_type, description, valid_from, modified_by_id_str, extra_options, log_callback, rebuild_ids, structural, source_context_root, change_data, data, None, source_item_id, rev_number, change)
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
                                                 extra_options,
                                                 source_context_root, rebuild_ids)
    if structural_lower == "наименование":
        return _apply_change_to_head(change, data, change_data, valid_from, rev_number, source_element, source_item_id, log_callback, extra_options, source_context_root)
    if structural_lower.endswith(' наименование') and structural_lower != 'наименование':
        element_part = structural[:-len(' наименование')].strip()
        change_copy = change.copy()
        change_copy['structural_element'] = f"наименование {element_part}"
        return _apply_change_to_element_head(change_copy, data, change_data, valid_from, rev_number, source_element, source_item_id, log_callback, extra_options, source_context_root, rebuild_ids)
    if structural_lower.startswith('наименование '):
        return _apply_change_to_element_head(change, data, change_data, valid_from, rev_number, source_element, source_item_id, log_callback, extra_options, source_context_root, rebuild_ids)
    if structural_lower == "преамбула":
        return _apply_change_to_preamble(change, data, change_data, valid_from, rev_number, source_element, source_item_id, log_callback, extra_options, source_context_root, rebuild_ids)
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
            modified_by_id_str = _resolve_modified_by_ids(rev_number, change_data, source_element, source_item_id, log_callback, structural_element=structural,  context_root=source_context_root)
            if modified_by_id_str is None:
                modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
            new_id = _add_new_element(parent_element, sys_type, child_num, cleaned_html, modified_by_id_str, valid_from, data, log_callback, rebuild_ids, ambiguous_callback, level_hint=2)
            return new_id is not None
        else:
            tokens = parse_structural_tokens(structural)
            if not tokens:
                log_callback(f"  Не удалось разобрать путь для add: {structural}", 'error')
                return False
            modified_by_id_str = _resolve_modified_by_ids(rev_number, change_data, source_element, source_item_id, log_callback, structural_element=structural,  context_root=source_context_root)
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
    modified_by_id_str = _resolve_modified_by_ids(rev_number, change_data, source_element, source_item_id, log_callback, structural_element=structural,  context_root=source_context_root)
    if not modified_by_id_str:
        modified_by_id_str = (source_item_id or str(change_data.get('npa_id', 'unknown')))
    return _apply_change_to_element_content(target_element, ch_type, description, valid_from, modified_by_id_str, extra_options, log_callback, rebuild_ids, structural, source_context_root, change_data, data, source_element, source_item_id, rev_number, change)

def _apply_change_to_appendix_prefix(change, data, change_data, valid_from, rev_number,
                                      source_element, source_item_id, log_callback,
                                      extra_options,
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
        answer = get_stage4_agent_answer(f"prefix_{app_element.get('item_id')}", log_callback)
        if answer:
            answer_html, _ = parse_stage4_answer(answer, log_callback)
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
        structural_element=structural,
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
                          extra_options,
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
            log_callback("  Запрос к агенту для нового заголовка...", 'info')
        answer = get_stage4_agent_answer("head", log_callback)
        if answer is None:
            if log_callback:
                log_callback("  Не удалось получить ответ агента для заголовка", 'error')
            return False
        answer_html, highlights = parse_stage4_answer(answer, log_callback)
        if not answer_html:
            if log_callback:
                log_callback("  Не удалось извлечь HTML из ответа агента", 'error')
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
        structural_element=change.get('structural_element', ''),
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
                                    extra_options,
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
        structural_element=structural,
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
        log_callback("  Запрос к агенту для изменения наименования...", 'info')
        answer_head = get_stage4_agent_answer(f"{target_element.get('item_id')}_head", log_callback)
        if answer_head is None:
            log_callback("  Не удалось получить ответ агента для наименования", 'error')
            return False
        answer_html, highlights = parse_stage4_answer(answer_head, log_callback)
        if not answer_html:
            log_callback("  Не удалось извлечь HTML из ответа агента", 'error')
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
                                extra_options,
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
        structural_element=change.get('structural_element', ''),
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
            log_callback("  Запрос к агенту для изменения преамбулы...", 'info')
        answer = get_stage4_agent_answer(f"{element.get('item_id')}_content", log_callback)
        if answer is None:
            if log_callback:
                log_callback("  Не удалось получить ответ агента", 'error')
            return False
        answer_html, highlights = parse_stage4_answer(answer, log_callback)
        if not answer_html:
            if log_callback:
                log_callback("  Не удалось извлечь HTML из ответа агента", 'error')
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
            log_callback("  Получен новый HTML от агента для преамбулы", 'result')
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
                                      log_callback, rebuild_ids,
                                      structural, source_context_root, change_data, data,
                                      source_element, source_item_id, rev_number,
                                      change=None):
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
                    log_callback("  Запрос к агенту для изменения элемента (с дочерними)...", 'info')
                answer = get_stage4_agent_answer("preamble", log_callback)
            if answer is None:
                if log_callback:
                    log_callback("  Не удалось получить ответ агента", 'error')
                return False
            answer_html, highlights = parse_stage4_answer(answer, log_callback)
            if not answer_html:
                if log_callback:
                    log_callback("  Не удалось извлечь HTML из ответа агента", 'error')
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
                log_callback("  Элемент обновлён через агента (сохранён HTML для перестройки)", 'result')
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
                    log_callback("  Запрос к агенту (промпт 4)...", 'info')
                answer = get_stage4_agent_answer(f"{element.get('item_id')}_content", log_callback)
                if answer is None:
                    if log_callback:
                        log_callback("  Не удалось получить ответ агента", 'error')
                    return False
                answer_html, highlights = parse_stage4_answer(answer, log_callback)
                if not answer_html:
                    if log_callback:
                        log_callback("  Не удалось извлечь HTML из ответа агента", 'error')
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
                    log_callback(f"  Получен новый HTML от агента (длина {len(answer_html)} символов)", 'result')
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


def apply_stage1_revocation(data, change, valid_from_dt, log_callback, source_npa_id=None, strict=False):
    """Применить изменение этапа 1 (утрата силы) к целевому документу."""
    structural_for_delete = change.get('structural_element_for_delete', '').strip()
    valid_from_str = change.get('valid_from', '')
    change_date = _parse_change_date(valid_from_str, valid_from_dt)
    mod_by = source_npa_id or str(data.get('npa_id', ''))
    if not mod_by:
        mod_by = str(data.get('npa_id', ''))

    if structural_for_delete == 'law' or structural_for_delete.lower() == 'закон':
        head_rev = data.get('head_revision', [])
        if not isinstance(head_rev, list) or not head_rev:
            log_callback("  Stage 1: head_revision отсутствует для утраты закона", 'error')
            return False
        active_idx = -1
        for i, rev in enumerate(head_rev):
            if rev.get('valid_to') in (None, ''):
                active_idx = i
                break
        if active_idx == -1 and head_rev:
            active_idx = len(head_rev) - 1
        valid_to_str = close_revision_date(change_date)
        if active_idx >= 0:
            head_rev[active_idx]['valid_to'] = valid_to_str
        head_rev.append({
            'npa_head': '',
            'mod_type': 'delete',
            'modified_by_id': mod_by,
            'valid_from': change_date.strftime('%d.%m.%Y'),
        })
        data['head_revision'] = head_rev
        log_callback("  Stage 1: утрата силы всего закона применена", 'result')
        return True

    target = None
    try:
        target = _find_existing_element_flexible(data, structural_for_delete, log_callback)
    except ValueError:
        if strict:
            log_callback(f"  Stage 1: неоднозначность для '{structural_for_delete}', отказ (strict)", 'error')
            return False
        target = None
    if not target:
        log_callback(f"  Stage 1: элемент не найден для утраты: {structural_for_delete}", 'error')
        return False
    revs = target.get('revisions', [])
    active_idx = -1
    for i, rev in enumerate(revs):
        if rev.get('valid_to') in (None, ''):
            active_idx = i
            break
    if active_idx == -1 and revs:
        active_idx = len(revs) - 1
    if active_idx >= 0:
        revs[active_idx]['valid_to'] = close_revision_date(change_date)
        revs[active_idx]['not_valid'] = mod_by
    new_rev = _make_new_revision([], mod_type='delete', modified_by_id=mod_by)
    new_rev['valid_from'] = change_date.strftime('%d.%m.%Y')
    revs.append(new_rev)
    target['revisions'] = revs
    log_callback(f"  Stage 1: утрата силы элемента '{structural_for_delete}' применена", 'result')
    return True


def apply_stage2_date_change(data, change, valid_from_dt, log_callback, source_npa_id=None, strict=False):
    """Применить изменение этапа 2 (специальные даты / ретроактивные notes)."""
    applies_to = change.get('applies_to', '').strip()
    action_type = change.get('action_type', '').strip()
    structural = change.get('structural_element', '').strip()
    special_date = change.get('date', '')
    change_date = _parse_change_date(special_date, valid_from_dt)
    mod_by = source_npa_id or str(data.get('npa_id', ''))

    target = None
    if applies_to == 'target_law' or applies_to == 'target':
        try:
            target = _find_existing_element_flexible(data, structural, log_callback)
        except ValueError:
            if strict:
                log_callback(f"  Stage 2: неоднозначность для '{structural}', отказ (strict)", 'error')
                return False
            target = None
    if action_type == 'special_valid_from':
        if target is None:
            log_callback(f"  Stage 2: элемент не найден для special_valid_from: {structural}", 'error')
            return False
        revs = target.get('revisions', [])
        active_idx = -1
        for i, rev in enumerate(revs):
            if rev.get('valid_to') in (None, ''):
                active_idx = i
                break
        if active_idx == -1 and revs:
            active_idx = len(revs) - 1
        if active_idx >= 0:
            revs[active_idx]['valid_to'] = close_revision_date(change_date)
        new_rev = {'mod_type': 'new_redaction', 'modified_by_id': mod_by,
                   'valid_from': change_date.strftime('%d.%m.%Y'), 'body': []}
        revs.append(new_rev)
        target['revisions'] = revs
        log_callback(f"  Stage 2: special_valid_from применена к '{structural}' с датой {change_date}", 'result')
        return True
    if action_type == 'retroactive_note':
        if target is None:
            log_callback(f"  Stage 2: элемент не найден для retroactive_note: {structural}", 'error')
            return False
        note_date = change.get('note_valid_from', special_date)
        note = {
            'text': f"Действие положений {structural} распространяется на правоотношения, "
                    f"возникшие с {note_date}",
            'valid_from': note_date,
            'valid_to': '',
        }
        notes = target.setdefault('item_notes', [])
        if not isinstance(notes, list):
            notes = []
        notes.append(note)
        target['item_notes'] = notes
        log_callback(f"  Stage 2: retroactive_note добавлен к '{structural}'", 'result')
        return True
    return False


def _parse_change_date(date_str, fallback_dt):
    if not date_str:
        return fallback_dt
    try:
        return datetime.strptime(date_str, '%d.%m.%Y').date()
    except (ValueError, TypeError):
        return fallback_dt

