"""Поиск элементов в документе."""

import re

from npa_processor.processing.text_utils import clean_number, safe_re_sub
from npa_processor.processing.tree_utils import find_item_by_id, parse_number_word, parse_revision_number_to_path

def _find_element_by_type_and_number(data, item_type, item_number, start_items=None, ambiguous_callback=None):
    if start_items is None:
        start_items = data.get('npa_items_revision', [])
    target_num_clean = clean_number(str(item_number)) if item_number is not None else None
    candidates = []
    for item in start_items:
        if item.get('item_type') == item_type:
            if item_number is None:
                if item_type in ('structured_table', 'appendix', 'preamble'):
                    match = True
                else:
                    match = (not item.get('item_number', ''))
            else:
                match = (clean_number(str(item.get('item_number', ''))) == target_num_clean)
            if match:
                candidates.append(item)
        child_items = item.get('item_children', [])
        if child_items:
            found = _find_element_by_type_and_number(data, item_type, item_number, child_items, ambiguous_callback)
            if found:
                candidates.append(found)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and ambiguous_callback:
        chosen_id = ambiguous_callback(item_type, item_number, candidates, '')
        if chosen_id is None:
            return None
        return next((c for c in candidates if c.get('item_id') == chosen_id), None)
    if len(candidates) > 0:
        raise ValueError(
            f"Неоднозначность для {item_type} {item_number}: найдено {len(candidates)} кандидатов, "
            "но ambiguous_callback не предоставлен или не вернул элемент."
        )
    return None

def find_item_by_revision_number(change_data, rev_number, context_root=None):
    if not rev_number:
        return None
    if isinstance(rev_number, list):
        for rn in rev_number:
            res = find_item_by_revision_number(change_data, rn, context_root)
            if res:
                return res
        return None
    if rev_number.lower() == 'null':
        return None
    path_parts = parse_revision_number_to_path(rev_number)
    if not path_parts:
        return None
    if context_root is not None:
        start_items = context_root.get('item_children', [])
    else:
        start_items = change_data.get('npa_items_revision', [])
    def search_in_items(items, parts):
        current_items = items
        found_item = None
        for _part in parts:
            part_clean_str = str(clean_number(_part)) if not isinstance(clean_number(_part), int) else str(clean_number(_part))
            found_item = None
            for item in current_items:
                item_num = item.get('item_number', '')
                item_clean_raw = clean_number(str(item_num))
                item_clean = str(item_clean_raw) if not isinstance(item_clean_raw, str) else item_clean_raw
                if item_clean == part_clean_str:
                    found_item = item
                    break
                if re.match(r'^[а-я]$', part_clean_str) and item_clean == part_clean_str + ')':
                    found_item = item
                    break
                if part_clean_str.endswith(')') and item_clean == part_clean_str[:-1]:
                    found_item = item
                    break
                if item_clean.endswith(')') and part_clean_str == item_clean[:-1]:
                    found_item = item
                    break
            if not found_item:
                return None
            current_items = found_item.get('item_children', [])
        return found_item.get('item_id') if found_item else None
    result = search_in_items(start_items, path_parts)
    return result

def _resolve_modified_by_ids(rev_number, change_data, source_element, source_item_id, log_callback,
                             structural_element='', context_root=None):
    if not rev_number or (isinstance(rev_number, str) and rev_number.lower() == 'null') or rev_number == []:
        if source_item_id:
            if log_callback:
                log_callback(f"  revision_number отсутствует, используем source_item_id = {source_item_id}", 'info')
            return source_item_id
        else:
            if log_callback:
                log_callback("  revision_number отсутствует и нет source_item_id", 'warning')
            return None
    modified_by_ids = []
    def find_id_for_rev(rev):
        if not rev or (isinstance(rev, str) and rev.lower() == 'null'):
            return None
        if any(w in str(rev).lower() for w in ['статья', 'пункт', 'часть', 'подпункт', 'абзац', 'глава', 'раздел', 'приложение']):
            try:
                from npa_processor.processing.element_ops import _find_existing_element_flexible
                elem = _find_existing_element_flexible(change_data, str(rev), log_callback)
                if elem:
                    return elem.get('item_id')
            except Exception as e:
                if log_callback:
                    log_callback(f"  Ошибка при поиске элемента по строке '{rev}': {e}", 'warning')
        return find_item_by_revision_number(change_data, rev, context_root=context_root)
    if isinstance(rev_number, list):
        for rev in rev_number:
            found_id = find_id_for_rev(rev)
            if found_id:
                found_id = narrow_source_id_to_subpoint(found_id, structural_element, change_data, log_callback)
                modified_by_ids.append(found_id)
    elif rev_number and isinstance(rev_number, str) and rev_number.lower() != 'null':
        found_id = find_id_for_rev(rev_number)
        if found_id:
            found_id = narrow_source_id_to_subpoint(found_id, structural_element, change_data, log_callback)
            modified_by_ids.append(found_id)
    if not modified_by_ids:
        if log_callback:
            log_callback(f"  Не удалось найти элемент по revision_number {rev_number}", 'error')
        return None
    return ', '.join(modified_by_ids) if modified_by_ids else None

def narrow_source_id_to_subpoint(coarse_id, structural_element, change_data, log_callback=None):
    source_elem = find_item_by_id(change_data, coarse_id)
    if not source_elem or not source_elem.get('item_children'):
        return coarse_id
    token_patterns = []
    for m in re.finditer(
        r'(часть|части|пункт[а-яё]*|стать[а-яё]+|подпункт[а-яё]*|абзац[а-яё]*|глав[а-яё]*|раздел[а-яё]*)'
        r'\s+(?:«?\s*([а-яё]|\d+(?:\.\d+)?)\s*»?)',
        structural_element, re.IGNORECASE
    ):
        prefix = m.group(1).lower()[:4]
        number = m.group(2)
        token_patterns.append((prefix, number))
    KEYWORD_MAP = {
        'наименование': ['наименовани'],
        'преамбул':     ['преамбул'],
        'статья':       ['стать'],
    }
    structural_lower = structural_element.lower().strip()
    keyword_patterns = []
    for key, needles in KEYWORD_MAP.items():
        if structural_lower.startswith(key):
            keyword_patterns = needles
            break
    if not token_patterns and not keyword_patterns:
        return coarse_id
    def _topic_header(elem):
        active_rev = next(
            (r for r in reversed(elem.get('revisions', [])) if not r.get('valid_to')),
            elem.get('revisions', [{}])[-1] if elem.get('revisions') else {}
        )
        for b in active_rev.get('body', []):
            if b.get('type') == 'paragraph' and b.get('html_text'):
                raw = safe_re_sub(r'<[^>]+>', '', b['html_text'])
                cut = re.search(r'[«]', raw)
                return (raw[:cut.start()] if cut else raw).lower()
        return ''
    def _match_score(text, patterns):
        score = 0
        for prefix, num in patterns:
            idx = text.find(num)
            while idx >= 0:
                after = text[idx + len(num): idx + len(num) + 1]
                if after and (after.isdigit() or after == '.'):
                    idx = text.find(num, idx + 1)
                    continue
                window = text[max(0, idx - 25): idx + len(num) + 5]
                if prefix in window:
                    score += 1
                    break
                idx = text.find(num, idx + 1)
        return score
    best_id = coarse_id
    best_score = 0
    best_level = -1
    def _keyword_score(text, needles):
        return sum(1 for n in needles if n in text)
    def _score(elem, level):
        nonlocal best_id, best_score, best_level
        text = _topic_header(elem)
        sc = _match_score(text, token_patterns) + _keyword_score(text, keyword_patterns)
        if sc > best_score or (sc == best_score and sc > 0 and level > best_level):
            best_score = sc
            best_id = elem.get('item_id', coarse_id)
            best_level = level
        for child in elem.get('item_children', []):
            _score(child, level + 1)
    for child in source_elem.get('item_children', []):
        _score(child, 1)
    if best_id != coarse_id and log_callback:
        log_callback(
            f"  Источник уточнён: {coarse_id} -> {best_id} (score={best_score})", 'info'
        )
    return best_id

def _extract_paragraph_order(structural):
    structural_lower = structural.lower()
    if 'абзац' not in structural_lower:
        return None
    abz_pattern = r'абзац[а-яё]*\s+(\d+|первый|второй|третий|четвертый|пятый|шестой|седьмой|восьмой|девятый|десятый)'
    match = re.search(abz_pattern, structural_lower)
    if match:
        num_str = match.group(1)
        if num_str.isdigit():
            return int(num_str)
        else:
            return parse_number_word(num_str)
    for i, part in enumerate(structural.split()):
        if part.lower().startswith('абзац') and i + 1 < len(structural.split()):
            num_str = structural.split()[i + 1].rstrip('.,;:')
            if num_str.isdigit():
                return int(num_str)
            word_num = parse_number_word(num_str)
            if word_num is not None:
                return word_num
    return None
