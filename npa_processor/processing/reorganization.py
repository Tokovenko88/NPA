"""Structural reorganization detection and application (article -> parts)."""

import os
import re

from bs4 import BeautifulSoup

from npa_processor.paths import SOURCE_DIR, load_json
from npa_processor.processing.element_ops import (
    _find_existing_element_flexible,
    close_revision_date,
)
from npa_processor.processing.html_utils import (
    extract_paragraphs_by_indices,
    get_full_element_html,
    remove_leading_number_from_html,
)


def detect_and_apply_structural_reorganization(all_changes, data, valid_from_dt, source_npa_id, log_callback, source_data=None):
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