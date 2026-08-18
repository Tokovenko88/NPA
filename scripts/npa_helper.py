#!/usr/bin/env python3
"""
NPA JSON Processor - Helper Tools
"""

import json
import os
import re
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_STATE_PATH = os.path.join(BASE_DIR, '.npa_gui_state.json')
ANSWERS_DIR = os.path.join(BASE_DIR, 'work', 'answers')
RESULT_DIR = os.path.join(BASE_DIR, 'work', 'results')

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_gui_state():
    if os.path.exists(GUI_STATE_PATH):
        try:
            return load_json(GUI_STATE_PATH)
        except Exception:
            return {}
    return {}

def save_gui_state(state):
    save_json(GUI_STATE_PATH, state)

def get_answers_dir():
    if not os.path.exists(ANSWERS_DIR):
        os.makedirs(ANSWERS_DIR)
    return ANSWERS_DIR

def get_result_dir(source_path=None):
    if source_path and os.path.exists(source_path):
        src_dir = os.path.dirname(os.path.abspath(source_path))
        expected_input_dir = os.path.join(BASE_DIR, 'work', 'source')
        if os.path.abspath(src_dir) == os.path.abspath(expected_input_dir):
            if not os.path.exists(RESULT_DIR):
                os.makedirs(RESULT_DIR)
            return RESULT_DIR
        return src_dir
    if not os.path.exists(RESULT_DIR):
        os.makedirs(RESULT_DIR)
    return RESULT_DIR

def date_add_days(date_str, days):
    d = datetime.strptime(date_str, '%d.%m.%Y')
    d += timedelta(days=days)
    return d.strftime('%d.%m.%Y')

def get_active_revision(item):
    for rev in item.get('revisions', []):
        if rev.get('valid_to') is None:
            return rev
    return item['revisions'][-1] if item['revisions'] else None

def close_revision_and_create_new(item, new_date, mod_type, modified_by_id, body=None, highlights=None, not_valid=None):
    active = get_active_revision(item)
    if active:
        active['valid_to'] = date_add_days(new_date, -1)
        if not_valid:
            active['not_valid'] = not_valid

    new_rev = {
        'valid_from': new_date,
        'valid_to': None,
        'modified_by_id': modified_by_id,
        'mod_type': mod_type,
        'body': body if body is not None else (active['body'] if active else []),
    }
    if highlights:
        new_rev['highlights'] = highlights
    item['revisions'].append(new_rev)
    return new_rev

def find_item_by_id(data, item_id):
    """Recursively find item by item_id in the document tree."""
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

def sync_parent_body_with_children(parent_item):
    """Ensure parent body has child_ref for all children in item_children."""
    if not parent_item:
        return
    children = parent_item.get('item_children', [])
    if not children:
        return
    active_rev = get_active_revision(parent_item)
    if not active_rev:
        return
    body = active_rev.get('body', [])
    for child in children:
        if not any(ref.get('item_id') == child.get('item_id') for ref in body):
            new_ref = {'type': 'child_ref', 'item_id': child.get('item_id'), 'order': len(body) + 1}
            body.append(new_ref)
    for idx, block in enumerate(body, 1):
        block['order'] = idx
    active_rev['body'] = body

def clean_number_for_filename(number):
    """Clean NPA number for filename, matching software project behavior."""
    if not number:
        return "unknown"
    number = str(number).strip()
    if number.startswith('№'):
        number = number[1:].strip()
    number = re.sub(r'[-–]\s*ЗС\s*(\d*)?$', '', number).strip()
    return number if number else "unknown"

def get_date_for_filename(data, doc_type='law'):
    """Extract date for filename in YYYY_MM_DD format, matching software project behavior."""
    if doc_type == 'law':
        date_str = data.get('date_signed', '')
    else:
        date_str = data.get('date_passed', '')
        if not date_str:
            date_str = data.get('date_reg', '')
    if not date_str:
        return datetime.now().strftime('%Y_%m_%d')
    try:
        dt = datetime.strptime(date_str, '%d.%m.%Y')
        return f"{dt.year:04d}_{dt.month:02d}_{dt.day:02d}"
    except ValueError:
        return datetime.now().strftime('%Y_%m_%d')

def generate_result_filename(target_data, source_data):
    """Generate correct result filename: {target_number}_{target_date}_izm_{source_number}_{source_date}.json"""
    orig_npa_number = target_data.get('npa_number', '')
    orig_clean_num = clean_number_for_filename(orig_npa_number)
    orig_doc_type = target_data.get('doc_type', target_data.get('npa_type', 'law'))
    orig_date = get_date_for_filename(target_data, orig_doc_type)

    change_npa_number = source_data.get('npa_number', '')
    change_clean_num = clean_number_for_filename(change_npa_number)
    change_doc_type = source_data.get('doc_type', source_data.get('npa_type', 'law'))
    change_date = get_date_for_filename(source_data, change_doc_type)

    return f"{orig_clean_num}_{orig_date}_izm_{change_clean_num}_{change_date}.json"

def remove_quotes(text, strip_html=False):
    """Remove outer quotes «» from text"""
    if strip_html:
        text = re.sub(r'<[^>]+>', '', text)
        text = text.strip()
        if text.startswith('«'):
            text = text[1:]
        if text.endswith('»;'):
            text = text[:-2] + ';'
        elif text.endswith('».'):
            text = text[:-2] + '.'
        elif text.endswith('»'):
            text = text[:-1]
        return text

    text = re.sub(r'(?<=>)«', '', text)
    text = re.sub(r'^\«', '', text)
    text = re.sub(r'»;(?=<)', ';', text)
    text = re.sub(r'».(?=<)', '.', text)
    text = re.sub(r'»(?=<)', '', text)
    return text

def extract_paragraphs(source_article, point_num, para_range):
    """Extract HTML paragraphs from source NPA article point"""
    for point in source_article.get('item_children', []):
        if point['item_number'] == point_num:
            body = point['revisions'][0]['body']
            start, end = map(int, para_range.split('-'))
            result = []
            for i, block in enumerate(body, 1):
                if start <= i <= end:
                    html = block.get('html_text', '')
                    if i == start or i == end:
                        html = remove_quotes(html, strip_html=False)
                    result.append({
                        'type': 'paragraph',
                        'html_text': html,
                        'order': len(result) + 1
                    })
            return result
    return []

def find_source_article(source_items, article_num):
    for article in source_items:
        if article['item_number'] == article_num:
            return article
    return None

if __name__ == '__main__':
    print("NPA JSON Processor - Helper Tools")
    print("Available functions:")
    print("  - load_json(path)")
    print("  - save_json(path, data)")
    print("  - date_add_days(date_str, days)")
    print("  - get_active_revision(item)")
    print("  - close_revision_and_create_new(item, new_date, mod_type, modified_by_id, body=None, highlights=None)")
    print("  - find_item_by_id(data, item_id)")
    print("  - sync_parent_body_with_children(parent_item)")
    print("  - generate_result_filename(target_data, source_data)")
