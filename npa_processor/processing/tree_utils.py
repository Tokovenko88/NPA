"""Утилиты для работы с деревом документа."""

import re

from npa_processor.processing.html_utils import add_number_to_paragraph_html, extract_text_from_element
from npa_processor.processing.text_utils import (
    clean_html_text,
    clean_number,
    normalize_text_for_search,
    parse_num,
    safe_re_sub,
    shift_highlight_index,
)


def find_item_by_id(data, item_id):
    def recurse(items):
        for item in items:
            if item.get('item_id') == item_id:
                return item
            if 'item_children' in item:
                found = recurse(item['item_children'])
                if found:
                    return found
        return None
    return recurse(data.get('npa_items_revision', []))


def parse_number_word(word):
    word = word.lower().rstrip('.,;:')
    mapping = {
        'первый': 1, 'первого': 1, 'первому': 1, 'первым': 1, 'первом': 1,
        'второй': 2, 'второго': 2, 'второму': 2, 'вторым': 2, 'втором': 2,
        'третий': 3, 'третьего': 3, 'третьему': 3, 'третьим': 3, 'третьем': 3,
        'четвертый': 4, 'четвертого': 4, 'четвертому': 4, 'четвертым': 4, 'четвертом': 4,
        'пятый': 5, 'пятого': 5, 'пятому': 5, 'пятым': 5, 'пятом': 5,
        'шестой': 6, 'шестого': 6, 'шестому': 6, 'шестым': 6, 'шестом': 6,
        'седьмой': 7, 'седьмого': 7, 'седьмому': 7, 'седьмым': 7, 'седьмом': 7,
        'восьмой': 8, 'восьмого': 8, 'восьмому': 8, 'восьмым': 8, 'восьмом': 8,
        'девятый': 9, 'девятого': 9, 'девятому': 9, 'девятым': 9, 'девятом': 9,
        'десятый': 10, 'десятого': 10, 'десятому': 10, 'десятым': 10, 'десятом': 10,
    }
    return mapping.get(word)

def parse_revision_number_to_path(rev_number, log_callback=None):
    if not rev_number:
        return None
    original = str(rev_number).strip()
    s = original.lower()
    s = safe_re_sub(r'\s*[–—>]\s*', '->', s)
    s = safe_re_sub(r'\)\s*->\s*', ')->', s)
    s = safe_re_sub(r'->+', '->', s)
    s = safe_re_sub(r'\s+', ' ', s).strip()
    s = safe_re_sub(r'(статья|ст\.|часть|ч\.|пункт|п\.|подпункт|пп\.|абзац|глава|гл\.|раздел|р\.)\s*', '', s)
    parts = []
    if '->' in s:
        parts = [p.strip() for p in s.split('->') if p.strip()]
    else:
        parts = [p.strip() for p in s.split() if p.strip()]
    cleaned = []
    for part in parts:
        part = part.strip(' .)')
        if not part:
            continue
        if part.isdigit() or re.match(r'^\d', part):
            part = safe_re_sub(r'[^0-9.]', '', part) + ')'
        elif re.match(r'^[а-яё]$', part):
            part = part + ')'
        else:
            part = part + ')'
        c = str(clean_number(part))
        if c:
            cleaned.append(c)
    if not cleaned or all(p == '' for p in cleaned):
        if log_callback:
            log_callback(f"Не удалось распознать revision_number '{original}' как путь к элементу", 'warning')
        return None
    return cleaned

def insert_child_ref_in_body(parent, new_child_id, log_callback=None):
    if parent is None:
        if log_callback:
            log_callback("  insert_child_ref_in_body: parent is None, пропуск вставки", 'warning')
        return
    revisions = parent.get('revisions', [])
    active_rev = None
    for rev in reversed(revisions):
        if rev.get('valid_to') in (None, ''):
            active_rev = rev
            break
    if active_rev is None:
        if revisions:
            active_rev = revisions[-1]
        else:
            active_rev = {'body': []}
            parent['revisions'] = [active_rev]
    body = active_rev.get('body', [])
    if any(b.get('type') == 'child_ref' and b.get('item_id') == new_child_id for b in body):
        return
    if parent.get('_pending_new_redaction_html') or parent.get('_pending_html'):
        return
    children = parent.get('item_children', [])
    new_pos = next((i for i, c in enumerate(children) if c.get('item_id') == new_child_id), None)
    if new_pos is None:
        if log_callback:
            log_callback(f"  insert_child_ref_in_body: {new_child_id} не найден в item_children", 'warning')
        return
    prev_child_id = children[new_pos - 1].get('item_id') if new_pos > 0 else None
    next_child_id = children[new_pos + 1].get('item_id') if new_pos + 1 < len(children) else None
    insert_after_idx = None
    insert_before_idx = None
    for i, block in enumerate(body):
        if block.get('type') == 'child_ref':
            if prev_child_id and block.get('item_id') == prev_child_id:
                insert_after_idx = i
            if next_child_id and block.get('item_id') == next_child_id:
                insert_before_idx = i
    if insert_after_idx is not None:
        insert_pos = insert_after_idx + 1
    elif insert_before_idx is not None:
        insert_pos = insert_before_idx
    else:
        last_ref_idx = -1
        for i, block in enumerate(body):
            if block.get('type') == 'child_ref':
                last_ref_idx = i
        insert_pos = last_ref_idx + 1 if last_ref_idx >= 0 else len(body)
    new_ref = {'type': 'child_ref', 'item_id': new_child_id, 'order': 0}
    body.insert(insert_pos, new_ref)
    for idx, block in enumerate(body, start=1):
        block['order'] = idx
    active_rev['body'] = body

def adjust_highlights_for_paragraph_change(highlights, op_type, target_idx, text_before="", text_after="", item_number=None, item_type=None):
    if highlights is None:
        highlights = {
            "previous_edition": {"deletion": [], "addition": [], "difference": []},
            "current_edition": {"deletion": [], "addition": [], "difference": []}
        }
    if target_idx == 1 and item_type in ('part', 'point', 'subpoint') and item_number:
        item_number = str(item_number)
        if text_before:
            text_before = add_number_to_paragraph_html(text_before, item_number, item_type)
        if text_after:
            text_after = add_number_to_paragraph_html(text_after, item_number, item_type)
    if op_type in ['add', 'delete']:
        delta = 1 if op_type == 'add' else -1
        curr = highlights.get("current_edition", {})
        for category in ["addition", "difference"]:
            if category in curr:
                for entry in curr[category]:
                    entry[1] = shift_highlight_index(entry[1], target_idx, delta)
    flat_before = clean_html_text(text_before)
    flat_after = clean_html_text(text_after)
    if op_type == 'add':
        highlights["current_edition"].setdefault("addition", []).append(
            [flat_after, f"{target_idx}-all"]
        )
    elif op_type == 'delete':
        highlights["previous_edition"].setdefault("deletion", []).append(
            [flat_before, f"{target_idx}-all"]
        )
    elif op_type == 'new_redaction' or op_type == 'change':
        highlights["previous_edition"].setdefault("deletion", []).append(
            [flat_before, f"{target_idx}-all"]
        )
        highlights["current_edition"].setdefault("addition", []).append(
            [flat_after, f"{target_idx}-all"]
        )
    return highlights

def _find_element_by_revision_path(root_element, revision_number):
    if not root_element or not revision_number:
        return None
    rev = str(revision_number).strip()
    normalized_rev = rev.lower()
    for word in ['подпункт', 'пункт', 'абзац', 'часть', 'статья', 'глава', 'раздел']:
        normalized_rev = safe_re_sub(r'\b' + word + r'\b\s*', '', normalized_rev)
    parts = re.split(r'[\s\)\.\-–—>]+', normalized_rev)
    parts = [p.strip(') .') for p in parts if p.strip()]
    if not parts:
        return None
    current = root_element
    for part in parts:
        found_child = None
        part_clean = clean_number(part) if 'clean_number' in globals() else part.strip(') .')
        for child in current.get('item_children', []):
            child_num = str(child.get('item_number', ''))
            child_clean = clean_number(child_num) if 'clean_number' in globals() else child_num.strip(') .')
            if child_clean == part_clean:
                found_child = child
                break
        if not found_child:
            for child in current.get('item_children', []):
                child_num = str(child.get('item_number', '')).strip()
                if child_num.rstrip(')') == part.rstrip(')'):
                    found_child = child
                    break
        if not found_child:
            return None
        current = found_child
    return current

def find_child_by_type_and_number(parent, child_type, child_number, ambiguous_callback=None):
    child_num_clean = None if child_number is None else clean_number(str(child_number))
    candidates = []
    for child in parent.get('item_children', []):
        if child.get('item_type') == child_type:
            if child_number is None:
                if child_type in ('structured_table', 'appendix', 'preamble'):
                    candidates.append(child)
                else:
                    if not child.get('item_number', ''):
                        candidates.append(child)
            else:
                if clean_number(str(child.get('item_number', ''))) == child_num_clean:
                    candidates.append(child)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and ambiguous_callback:
        chosen_id = ambiguous_callback(child_type, child_number, candidates, '')
        if chosen_id is None:
            return None
        return next((c for c in candidates if c.get('item_id') == chosen_id), None)
    if len(candidates) > 0:
        raise ValueError(
            f"Неоднозначность для {child_type} {child_number}: найдено {len(candidates)} кандидатов, "
            "но ambiguous_callback не предоставлен или не вернул элемент."
        )
    return None

def find_element_in_chapters_or_sections(parent, target_type, target_number, log_callback=None, ambiguous_callback=None):
    chapters_or_sections = [ch for ch in parent.get('item_children', []) if ch.get('item_type') in ('chapter', 'section')]
    if not chapters_or_sections:
        return None, None
    for ch in chapters_or_sections:
        found = find_child_by_type_and_number(ch, target_type, target_number, ambiguous_callback)
        if found:
            return ch, found
    if target_number and '.' in str(target_number):
        base_num = str(target_number).split('.')[0]
        for ch in chapters_or_sections:
            if find_child_by_type_and_number(ch, target_type, base_num, ambiguous_callback):
                if log_callback:
                    type_name = 'главе' if ch.get('item_type') == 'chapter' else 'разделе'
                    log_callback(f"  {type_name.capitalize()} для {target_type} {target_number} определена по базовому номеру {base_num}: {type_name.capitalize()} {ch.get('item_number')}", 'info')
                return ch, None
    target_val = parse_num(target_number)
    best_chapter = chapters_or_sections[0] if chapters_or_sections else None
    best_max_val = (0,)
    for ch in chapters_or_sections:
        ch_max_val = (0,)
        for child in ch.get('item_children', []):
            if child.get('item_type') == target_type:
                val = parse_num(child.get('item_number', ''))
                if val > ch_max_val:
                    ch_max_val = val
        if ch_max_val != (0,) and ch_max_val <= target_val and ch_max_val > best_max_val:
            best_max_val = ch_max_val
            best_chapter = ch
    return best_chapter, None



def find_target_element(change_data, original_data, log_callback, doc_type='law'):
    return _find_target_element(change_data, original_data, log_callback, doc_type, ambiguous_callback=None)


def _find_target_element(change_data, original_data, log_callback, doc_type='law', ambiguous_callback=None):
    original_number = original_data.get('npa_number', '')
    clean_number = safe_re_sub(r'[^0-9]', '', original_number)
    if not clean_number:
        if log_callback:
            log_callback("Не удалось извлечь номер оригинального НПА", 'error')
        return None
    required_words = [clean_number]
    if doc_type == 'regulation':
        required_words.append('постановлени')
        date_str = original_data.get('date_passed', '') or original_data.get('date_reg', '')
        if date_str:
            year = date_str.split('.')[-1]
            if year and year.isdigit():
                required_words.append(year)
    else:
        required_words.append('закон')
    if log_callback:
        log_callback(f"  Поиск по ключевым словам (с корнями): {required_words}", 'debug')
    def search_in_items(items):
        for item in items:
            text = extract_text_from_element(item)
            norm_text = normalize_text_for_search(text)
            if all(word in norm_text for word in required_words):
                if log_callback:
                    log_callback(f"  Найден элемент {item.get('item_type')} {item.get('item_number')} (ID {item.get('item_id')})", 'result')
                return item
            child_result = search_in_items(item.get('item_children', []))
            if child_result:
                return child_result
        return None
    root_items = change_data.get('npa_items_revision', [])
    return search_in_items(root_items)


def find_appendix_by_number(data, app_number):
    if not data or not app_number:
        return None
    app_number = str(app_number).strip()
    def _search(items):
        for item in items:
            if item.get('item_type') == 'appendix':
                item_num = str(item.get('item_number', '')).strip()
                if clean_number(item_num) == clean_number(app_number):
                    return item
            child = _search(item.get('item_children', []))
            if child:
                return child
        return None
    return _search(data.get('npa_items_revision', []))


