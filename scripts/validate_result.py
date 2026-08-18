import json
import re
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULT_PATH = os.path.join(BASE_DIR, 'work', 'results', '269_2016_07_27_izm_380_2017_12_04.json')

with open(RESULT_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

errors = []
ids = []

def collect_ids(items):
    for item in items:
        ids.append(item.get('item_id'))
        if 'item_children' in item:
            collect_ids(item['item_children'])

collect_ids(data.get('npa_items_revision', []))
if len(ids) != len(set(ids)):
    errors.append('Duplicate item_ids found')

def check_revisions(items):
    for item in items:
        active = [r for r in item.get('revisions', []) if r.get('valid_to') is None]
        if len(active) > 1:
            errors.append(f"{item.get('item_id')} has {len(active)} active revisions")
        if 'item_children' in item:
            check_revisions(item['item_children'])

check_revisions(data.get('npa_items_revision', []))

def check_refs(items):
    for item in items:
        active = [r for r in item.get('revisions', []) if r.get('valid_to') is None]
        if not active:
            active = item.get('revisions', [])[-1:] if item.get('revisions') else []
        for rev in active:
            for block in rev.get('body', []):
                if block.get('type') == 'child_ref':
                    ref_id = block.get('item_id')
                    if ref_id not in ids:
                        errors.append(f"Broken child_ref: {item.get('item_id')} -> {ref_id}")
        if 'item_children' in item:
            check_refs(item['item_children'])

check_refs(data.get('npa_items_revision', []))

def check_dates(items):
    for item in items:
        for rev in item.get('revisions', []):
            vf = rev.get('valid_from', '')
            vt = rev.get('valid_to', '')
            if vf and not re.match(r'^\d{2}\.\d{2}\.\d{4}$', vf):
                errors.append(f"Bad valid_from date: {vf} in {item.get('item_id')}")
            if vt and not re.match(r'^\d{2}\.\d{2}\.\d{4}$', vt):
                errors.append(f"Bad valid_to date: {vt} in {item.get('item_id')}")
        if 'item_children' in item:
            check_dates(item['item_children'])

check_dates(data.get('npa_items_revision', []))

if errors:
    print('ERRORS:')
    for e in errors:
        print(' ', e)
else:
    print('All validation checks passed!')

print(f'Total items: {len(ids)}')
print(f'Unique item_ids: {len(set(ids))}')
