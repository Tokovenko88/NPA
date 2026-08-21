"""Операции над элементами дерева НПА (поиск, добавление, rebuild)."""

import copy
import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from npa_processor.core.html_parser import NpaToJsonGenerator
from npa_processor.processing.element_finder import find_item_by_revision_number
from npa_processor.processing.html_utils import (
    clean_and_unwrap_html,
    clean_description_html,
    create_element_skeleton,
    get_full_element_html,
    parse_structural_tokens,
    remove_leading_number_from_html,
    split_html_to_paragraphs,
)
from npa_processor.processing.identity import are_structural_elements_identical
from npa_processor.processing.revision_builder import sync_parent_body_with_children
from npa_processor.processing.text_utils import (
    clean_head_text,
    clean_html_text,
    close_revision_date,
    get_element_text,
    normalize_item_number,
    parse_num,
    safe_re_sub,
)
from npa_processor.processing.tree_utils import (
    find_child_by_type_and_number,
    find_element_in_chapters_or_sections,
    find_item_by_id,
    find_parent,
    insert_child_ref_in_body,
    match_item_type_and_number,
)

_ETYPE_WORDS = {
    'часть': 'часть', 'части': 'часть',
    'пункт': 'пункт', 'пункты': 'пункт', 'пункта': 'пункт',
    'подпункт': 'подпункт', 'подпункты': 'подпункт',
    'статья': 'статья', 'статьи': 'статья', 'статью': 'статья',
    'абзац': 'абзац', 'абзацы': 'абзац',
    'глава': 'глава', 'главы': 'глава',
    'раздел': 'раздел', 'разделы': 'раздел',
    'приложение': 'приложение', 'приложения': 'приложение',
}

def normalize_ru_type(ru_type):
    return _ETYPE_WORDS.get(ru_type, ru_type)


def collect_item_ids(item, ids_set):
    if 'item_id' in item:
        ids_set.add(item['item_id'])
    for child in item.get('item_children', []):
        collect_item_ids(child, ids_set)


def _fetch_source_html_for_change(change, change_data, target_element, log_callback):
    rev_number = change.get('revision_number')
    if not rev_number or rev_number == 'null':
        if target_element:
            if log_callback:
                log_callback(f"  revision_number == null, берём HTML из target_element (ID {target_element.get('item_id')})", 'info')
            return get_full_element_html(target_element, include_header=False)
        else:
            return None
    rev_list = rev_number if isinstance(rev_number, list) else [rev_number]
    for rn in rev_list:
        source_id = find_item_by_revision_number(change_data, rn, context_root=target_element)
        if source_id:
            source_elem = find_item_by_id(change_data, source_id)
            if source_elem:
                if log_callback:
                    log_callback(f"  Найден элемент-источник по revision_number {rn} -> ID {source_id}", 'result')
                return get_full_element_html(source_elem, include_header=False)
    return None

def _child_with_key_exists_in_new_tree(child_type, child_number, new_element):
    if not new_element:
        return False
    if (new_element.get('item_type'), new_element.get('item_number')) == (child_type, child_number):
        return True
    for child in new_element.get('item_children', []):
        if _child_with_key_exists_in_new_tree(child_type, child_number, child):
            return True
    return False

def _item_id_exists_in_new_tree(item_id, new_element):
    if not new_element:
        return False
    if new_element.get('item_id') == item_id:
        return True
    return any(_item_id_exists_in_new_tree(item_id, child) for child in new_element.get('item_children', []))

def _item_key_exists_in_new_tree(item_type, item_number, new_element):
    if not new_element:
        return False
    if new_element.get('item_type') == item_type and new_element.get('item_number') == item_number:
        return True
    for child in new_element.get('item_children', []):
        if _item_key_exists_in_new_tree(item_type, item_number, child):
            return True
    return False

def _transfer_structural_state(old_child, new_child, log_callback=None):
    """Переносит историю и отложенные (pending) изменения со старого элемента на новый.

    Используется при смене родителя, напр. когда законодатель добавил '1.' к первому
    абзацу статьи и парсер создал новую 'часть', в которую «вложились» бывшие прямые
    пункты. Без переноса изменённые пункты потерялись бы (стали осиротевшими и помечены
    удалёнными), а в новой части появились бы свежие НЕизменённые пункты.
    """
    if old_child is None or new_child is None:
        return
    for attr in ['_pending_new_redaction_html', '_pending_html', '_pending_mod_type',
                 '_pending_modified_by_id', '_pending_valid_from', '_pending_highlights']:
        if attr in old_child:
            new_child[attr] = old_child[attr]
    if old_child.get('revisions'):
        new_child['revisions'] = copy.deepcopy(old_child['revisions'])
    if old_child.get('head_revisions'):
        new_child['head_revisions'] = copy.deepcopy(old_child['head_revisions'])
    if old_child.get('item_notes'):
        new_child['item_notes'] = copy.deepcopy(old_child['item_notes'])
    old_childs = old_child.get('item_children', [])
    new_childs = new_child.get('item_children', [])
    old_by = {(c.get('item_type'), c.get('item_number')): c for c in old_childs}
    new_by = {(c.get('item_type'), c.get('item_number')): c for c in new_childs}
    for k in set(old_by.keys()) & set(new_by.keys()):
        _transfer_structural_state(old_by[k], new_by[k], log_callback)

def sync_structural_element_recursive(old_element, new_element, change_date, modified_by_id, data_context, log_callback, is_top_level=True, override_mod_type=None, highlights=None, is_table_child=False):
    valid_from_dt = datetime.strptime(change_date, '%d.%m.%Y')
    valid_to_prev = close_revision_date(valid_from_dt)
    old_children = old_element.setdefault('item_children', [])
    new_children = new_element.get('item_children', [])
    old_by_key = {(c.get('item_type'), c.get('item_number')): c for c in old_children}
    new_by_key = {(c.get('item_type'), c.get('item_number')): c for c in new_children}
    all_keys = set(old_by_key.keys()) | set(new_by_key.keys())
    moved_keys = set()
    for key in all_keys:
        if key in old_by_key and key in new_by_key:
            old_child = old_by_key[key]
            new_child_source = new_by_key[key]
            sync_structural_element_recursive(
                old_child, new_child_source, change_date, modified_by_id,
                data_context, log_callback, is_top_level=False,
                override_mod_type=override_mod_type, is_table_child=is_table_child
            )
            identical = are_structural_elements_identical(old_child, new_child_source)
            if (
                not new_child_source.get('revisions')
                and old_child.get('revisions')
                and identical
            ):
                old_active_rev = None
                for rev in reversed(old_child['revisions']):
                    if rev.get('valid_to') is None:
                        old_active_rev = rev
                        break
                if old_active_rev is not None:
                    new_child_source['revisions'] = [copy.deepcopy(old_active_rev)]
                    if log_callback:
                        log_callback(f"  Активная ревизия перенесена из {old_child.get('item_id')} в {new_child_source.get('item_id')}", 'result')
            elif old_child.get('revisions') and identical:
                old_active_rev = None
                for rev in reversed(old_child['revisions']):
                    if rev.get('valid_to') is None:
                        old_active_rev = rev
                        break
                if old_active_rev is not None and (old_active_rev.get('mod_type') or old_active_rev.get('modified_by_id')):
                    new_child_source['revisions'] = [copy.deepcopy(old_active_rev)]
                    if log_callback:
                        log_callback(f"  Активная ревизия с изменениями перенесена из {old_child.get('item_id')} в {new_child_source.get('item_id')}", 'result')
            new_child_grandchildren = new_child_source.get('item_children', [])
            if new_child_grandchildren:
                new_grand_by_key = {(c.get('item_type'), c.get('item_number')): c for c in new_child_grandchildren}
                old_parent_children = old_element.get('item_children', [])
                old_parent_by_key = {(c.get('item_type'), c.get('item_number')): c for c in old_parent_children}
                children_moved = False
                for del_key in list(old_parent_by_key.keys()):
                     if del_key in new_grand_by_key and del_key not in moved_keys:
                         old_direct = old_parent_by_key[del_key]
                         grand_source = new_grand_by_key[del_key]
                         old_grand = None
                         for c in old_child.get('item_children', []):
                             if (c.get('item_type'), c.get('item_number')) == del_key:
                                 old_grand = c
                                 break
                         if old_grand and any(rev.get('valid_from') or rev.get('mod_type') for rev in old_grand.get('revisions', [])):
                             continue
                         if old_grand:
                             _transfer_structural_state(old_direct, old_grand, log_callback)
                             moved_keys.add(del_key)
                             children_moved = True
                             if log_callback:
                                 log_callback(f"  Перенесено состояние ребёнка {del_key[0]} {del_key[1]} (ID {old_direct.get('item_id')}) в контейнер {key[0]} {key[1]} -> {del_key[0]} {del_key[1]} (ID {old_grand.get('item_id')})", 'result')
                if children_moved:
                    container_revisions = old_child.get('revisions', [])
                    active_container_rev = None
                    for rev in reversed(container_revisions):
                        if rev.get('valid_to') is None:
                            active_container_rev = rev
                            break
                    if active_container_rev:
                        old_body = active_container_rev.get('body', [])
                        non_ref_blocks = [b for b in old_body if b.get('type') != 'child_ref']
                        new_body = list(non_ref_blocks)
                        for child in old_child.get('item_children', []):
                            new_body.append({'type': 'child_ref', 'item_id': child.get('item_id'), 'order': len(new_body) + 1})
                        for idx, block in enumerate(new_body, 1):
                            block['order'] = idx
                        active_container_rev['body'] = new_body
    for key in all_keys:
        if key not in old_by_key and key in new_by_key:
            new_child_source = new_by_key[key]
            new_child_grandchildren = new_child_source.get('item_children', [])
            if new_child_grandchildren:
                new_grand_by_key = {(c.get('item_type'), c.get('item_number')): c for c in new_child_grandchildren}
                for del_key in list(old_by_key.keys()):
                    if del_key in new_by_key:
                        continue
                    if del_key in new_grand_by_key and del_key not in moved_keys:
                        old_child = old_by_key[del_key]
                        grand_source = new_grand_by_key[del_key]
                        if any(rev.get('valid_from') or rev.get('mod_type') for rev in grand_source.get('revisions', [])):
                            continue
                        child_revs = old_child.setdefault('revisions', [])
                        active_rev = None
                        for rev in reversed(child_revs):
                            if rev.get('valid_to') is None:
                                active_rev = rev
                                break
                        if active_rev is not None:
                            active_rev['valid_to'] = valid_to_prev
                            active_rev['not_valid'] = modified_by_id
                        grand_source_revs = grand_source.setdefault('revisions', [])
                        active_grand_rev = None
                        for rev in reversed(grand_source_revs):
                            if rev.get('valid_to') is None:
                                active_grand_rev = rev
                                break
                        if active_grand_rev is not None and active_rev is not None:
                            active_grand_rev['body'] = copy.deepcopy(active_rev.get('body', []))
                        elif active_rev is not None or active_rev is not None:
                            new_rev = copy.deepcopy(active_rev)
                            new_rev.pop('valid_to', None)
                            new_rev.pop('not_valid', None)
                            if 'valid_from' in new_rev:
                                del new_rev['valid_from']
                            grand_source['revisions'] = [new_rev]
                            if log_callback:
                                log_callback(f"  Создана активная ревизия для {grand_source.get('item_id')} на основе старой ревизии {old_child.get('item_id')}", 'result')
                        if old_child.get('head_revisions'):
                            old_head_revs = old_child['head_revisions']
                            active_hr = None
                            for hr in reversed(old_head_revs):
                                if hr.get('valid_to') is None:
                                    active_hr = hr
                                    break
                            if active_hr is not None:
                                active_hr['valid_to'] = valid_to_prev
                            current_head_text = active_hr.get('head_text', '') if active_hr else ''
                            grand_source_head_revs = grand_source.setdefault('head_revisions', [])
                            active_grand_hr = None
                            for hr in reversed(grand_source_head_revs):
                                if hr.get('valid_to') is None:
                                    active_grand_hr = hr
                                    break
                            if active_grand_hr is not None:
                                active_grand_hr['head_text'] = current_head_text
                            else:
                                grand_source_head_revs.append({
                                    'head_text': current_head_text,
                                })
                        if old_child.get('item_notes') and 'item_notes' not in grand_source:
                            grand_source['item_notes'] = copy.deepcopy(old_child['item_notes'])
                        moved_keys.add(del_key)
                        if log_callback:
                            log_callback(f"  Закрыта старая ревизия пункта {old_child.get('item_id')} (бывш. ребёнок {key[0]} {key[1]}) и переданы данные в {grand_source.get('item_id')}", 'result')
            for _nc_rev in new_child_source.get('revisions', []):
                old_body = _nc_rev.get('body', [])
                non_ref_blocks = [b for b in old_body if b.get('type') != 'child_ref']
                new_body = list(non_ref_blocks)
                for m_child in new_child_source.get('item_children', []):
                    new_body.append({'type': 'child_ref', 'item_id': m_child.get('item_id'), 'order': len(new_body) + 1})
                for idx, block in enumerate(new_body, 1):
                    block['order'] = idx
                _nc_rev['body'] = new_body
            for attr in ['_pending_new_redaction_html', '_pending_mod_type', '_pending_modified_by_id', '_pending_valid_from']:
                new_child_source.pop(attr, None)
            old_children.append(new_child_source)
            # ИСПРАВЛЕНИЕ: синхронизируем тело родителя, чтобы добавить child_ref на нового ребёнка
            sync_parent_body_with_children(old_element, log_callback)
            if log_callback:
                log_callback(f"  Добавлен новый ребёнок {key[0]} {key[1]} (ID {new_child_source.get('item_id')})", 'result')
    for key in all_keys:
        if key in old_by_key and key not in new_by_key:
            if key in moved_keys:
                continue
            old_child = old_by_key[key]
            if old_child.get('_pending_new_redaction_html') or old_child.get('_pending_html'):
                continue
            is_added = any(
                rev.get('mod_type') == 'add' and rev.get('valid_from') and not rev.get('valid_to')
                for rev in old_child.get('revisions', [])
            )
            is_placeholder = old_child.get('_precreated_placeholder', False)
            if is_added or is_placeholder:
                if is_placeholder:
                    old_child['revisions'] = []
                    old_child.pop('_precreated_placeholder', None)
                    if log_callback:
                        log_callback(f"  Фантомная add-ревизия плейсхолдера {old_child.get('item_id')} удалена", 'info')
                    if not old_child.get('item_children') and not old_child.get('head_revisions'):
                        if log_callback:
                            log_callback(f"  Плейсхолдер {old_child.get('item_id')} ({old_child.get('item_type')} {old_child.get('item_number')}) удаляется (нет дочерних элементов)", 'info')
                        continue
                else:
                    if log_callback:
                        log_callback(f"  Добавленный элемент {old_child.get('item_id')} не найден в новой структуре, оставляем как есть", 'info')
                    continue
            if _item_key_exists_in_new_tree(old_child.get('item_type'), old_child.get('item_number'), new_element):
                found_new = None
                stack = [new_element]
                while stack:
                    candidate = stack.pop(0)
                    if candidate.get('item_type') == old_child.get('item_type') and candidate.get('item_number') == old_child.get('item_number'):
                        found_new = candidate
                        break
                    stack.extend(candidate.get('item_children', []))
                if found_new is not None:
                    if are_structural_elements_identical(old_child, found_new):
                        _transfer_structural_state(old_child, found_new, log_callback)
                        moved_keys.add(key)
                        if old_child in old_children:
                            old_children.remove(old_child)
                        if log_callback:
                            log_callback(f"  Перенесено состояние {key[0]} {key[1]} (ID {old_child.get('item_id')}) в новый элемент {found_new.get('item_id')}", 'result')
                    else:
                        if log_callback:
                            log_callback(f"  Ребёнок {key[0]} {key[1]} (ID {old_child.get('item_id')}) найден в новом дереве, но содержание отличается. Закрываем старую ревизию.", 'info')
                    continue
            if not _item_key_exists_in_new_tree(old_child.get('item_type'), old_child.get('item_number'), new_element) and log_callback:
                log_callback(f"  Ребёнок {key[0]} {key[1]} (ID {old_child.get('item_id')}) не найден в новом дереве по ключу, закрываем ревизию", 'info')
            child_revs = old_child.setdefault('revisions', [])
            active_rev = None
            for rev in reversed(child_revs):
                if rev.get('valid_to') is None:
                    active_rev = rev
                    break
            if active_rev is not None:
                active_rev['valid_to'] = valid_to_prev
                active_rev['not_valid'] = modified_by_id
            else:
                # Элемент не имеет активной ревизии. Это возможно в двух случаях:
                # 1) элемент уже утратил силу (есть ревизия с not_valid) — повторно
                #    удалять его не нужно, иначе создастся противоречивый маркер;
                # 2) элемент никогда не имел ревизий.
                already_not_valid = any(rev.get('not_valid') is not None for rev in child_revs)
                if already_not_valid:
                    continue
                child_revs.append({
                    'body': [],
                    'valid_to': valid_to_prev,
                    'not_valid': modified_by_id
                })
            if log_callback:
                log_callback(f"  Ребёнок {key[0]} {key[1]} помечен как удалённый", 'result')
    ordered = []
    for new_child in new_children:
        key = (new_child.get('item_type'), new_child.get('item_number'))
        if key in old_by_key:
            ordered.append(old_by_key[key])
        else:
            for c in old_children:
                if c.get('item_id') == new_child.get('item_id'):
                    ordered.append(c)
                    break
    for c in old_children:
        if c not in ordered:
            ordered.append(c)
    filtered_ordered = []
    for child in ordered:
        key = (child.get('item_type'), child.get('item_number'))
        if key in old_by_key and key not in new_by_key and not child.get('_pending_new_redaction_html') and not child.get('_pending_html') and _item_key_exists_in_new_tree(child.get('item_type'), child.get('item_number'), new_element):
            continue
        filtered_ordered.append(child)
    old_element['item_children'] = filtered_ordered
    if is_table_child and old_element.get('item_type') in ('section', 'point', 'subpoint'):
        old_num = old_element.get('item_number', '')
        new_num = new_element.get('item_number') or new_element.get('number', '')
        if new_num and str(new_num) != str(old_num):
            if 'number_revisions' not in old_element:
                old_element['number_revisions'] = []
            def get_earliest_valid_from(element):
                revs = element.get('revisions', [])
                for rev in revs:
                    if rev.get('valid_from'):
                        return rev['valid_from']
                return change_date
            if not old_element['number_revisions']:
                valid_from_old = get_earliest_valid_from(old_element)
                old_element['number_revisions'].append({
                    'number_text': old_num,
                    'valid_from': valid_from_old,
                    'valid_to': valid_to_prev
                })
            else:
                for rev in old_element['number_revisions']:
                    if rev.get('valid_to') is None:
                        rev['valid_to'] = valid_to_prev
                        break
            mod_type_num = 'new_redaction' if override_mod_type == 'new_redaction' else 'change'
            old_element['number_revisions'].append({
                'number_text': new_num,
                'valid_from': change_date,
                'mod_type': mod_type_num,
                'modified_by_id': modified_by_id
            })
            old_element['item_number'] = new_num
            if log_callback:
                log_callback(f"  Номер элемента изменён: {old_num} -> {new_num} (запись в number_revisions)", 'result')
    new_body = []
    if new_element.get('collected_content'):
        for idx, content in enumerate(new_element['collected_content'], 1):
            new_body.append({'type': 'paragraph', 'html_text': content, 'order': idx})
    elif new_element.get('revisions') and new_element['revisions']:
        new_body = copy.deepcopy(new_element['revisions'][0].get('body', []))
    if new_body is None:
        new_body = []
    for child in old_element.get('item_children', []):
        if override_mod_type == 'new_redaction':
            continue
        if child.get('_pending_new_redaction_html') or child.get('_pending_html'):
            child_id = child.get('item_id')
            if not any(b.get('type') == 'child_ref' and b.get('item_id') == child_id for b in new_body):
                child_type = child.get('item_type')
                child_number = child.get('item_number')
                if not _child_with_key_exists_in_new_tree(child_type, child_number, new_element):
                    new_body.append({'type': 'child_ref', 'item_id': child_id, 'order': len(new_body) + 1})
    new_head = None
    if old_element.get('item_type') in ('article', 'chapter', 'section', 'appendix'):
        explicit_head_revs = new_element.get('head_revisions', [])
        if explicit_head_revs:
            for rev in reversed(explicit_head_revs):
                if rev.get('valid_to') is None:
                    new_head = rev.get('head_text')
                    break
            if new_head is None and explicit_head_revs:
                new_head = explicit_head_revs[-1].get('head_text')
            if new_head is not None:
                new_head = clean_head_text(new_head, old_element.get('item_type'), str(old_element.get('item_number', '')))
    if new_head and new_body:
        first_block = new_body[0]
        if first_block.get('type') == 'paragraph':
            first_text = clean_html_text(first_block.get('html_text', ''))
            first_cleaned = clean_head_text(first_text, old_element.get('item_type', ''), str(old_element.get('item_number', '')))
            if first_cleaned == new_head:
                new_body.pop(0)
                for idx, block in enumerate(new_body, 1):
                    block['order'] = idx
    old_child_ids_before = [c.get('item_id') for c in old_children]
    old_child_ids_after = [c.get('item_id') for c in old_element.get('item_children', [])]
    children_changed = (old_child_ids_before != old_child_ids_after)
    current_text = get_element_text(old_element)
    new_text = ''
    for block in new_body:
        if block.get('type') == 'paragraph':
            html = block.get('html_text', '')
            new_text += clean_html_text(html) + ' '
        elif block.get('type') == 'table_fragment' and is_table_child:
            new_text = 'dummy_non_empty_text'
    new_text = ' '.join(new_text.split())
    if (not is_table_child
        and current_text == new_text
        and new_head is None
        and not children_changed
        and not hasattr(old_element, '_force_rebuild')):
        if override_mod_type != 'add':
            if log_callback:
                log_callback(f"  Содержимое элемента {old_element.get('item_id')} не изменилось, новая ревизия не создаётся", 'info')
            return
        else:
            if log_callback:
                log_callback(f"  Элемент {old_element.get('item_id')} добавлен, создаём ревизию с пустым body", 'info')
    if old_element.get('item_type') in ('article', 'chapter', 'section', 'appendix') and new_head is not None:
            head_revisions = old_element.setdefault('head_revisions', [])
            active_idx = -1
            for i, rev in enumerate(head_revisions):
                if rev.get('valid_to') is None:
                    active_idx = i
                    break
            if active_idx == -1 and head_revisions:
                active_idx = len(head_revisions) - 1
            current_head_raw = head_revisions[active_idx].get('head_text', '') if active_idx != -1 else ''
            current_head_cleaned = clean_head_text(current_head_raw, old_element.get('item_type'), str(old_element.get('item_number', '')))
            if active_idx == -1:
                if override_mod_type in ('add', 'new_redaction'):
                    head_rev = {'head_text': new_head}
                else:
                    head_mod_type = override_mod_type if override_mod_type else 'add'
                    head_rev = {
                        'head_text': new_head,
                        'mod_type': head_mod_type,
                        'modified_by_id': modified_by_id
                    }
                    if head_mod_type == 'add':
                        head_rev['valid_from'] = change_date
                if highlights is not None and not is_highlights_empty(highlights):
                    head_rev['highlights'] = highlights
                head_revisions.append(head_rev)
                if log_callback:
                    log_callback(f"  Первая запись заголовка добавлена: '{new_head}'", 'result')
            else:
                if current_head_cleaned != new_head:
                    if head_revisions[active_idx].get('valid_to') is None:
                        head_revisions[active_idx]['valid_to'] = valid_to_prev
                    if override_mod_type in ('add', 'new_redaction'):
                        head_rev = {'head_text': new_head}
                    else:
                        head_mod_type = override_mod_type if override_mod_type else 'change'
                        head_rev = {
                            'head_text': new_head,
                            'mod_type': head_mod_type,
                            'modified_by_id': modified_by_id
                        }
                        if head_mod_type == 'add':
                            head_rev['valid_from'] = change_date
                    if highlights is not None and not is_highlights_empty(highlights):
                        head_rev['highlights'] = highlights
                    head_revisions.append(head_rev)
                    if log_callback:
                        log_callback(f"  Заголовок обновлён: '{current_head_cleaned}' -> '{new_head}'", 'result')
    if old_element.get('item_type') == 'appendix':
        old_prefix_revs = old_element.setdefault('item_prefix_revisions', [])
        new_prefix_revs = new_element.get('item_prefix_revisions', [])
        old_active_prefix = None
        old_active_idx = -1
        for i, rev in enumerate(old_prefix_revs):
            if rev.get('valid_to') is None:
                old_active_prefix = rev.get('prefix_text', '')
                old_active_idx = i
                break
        if old_active_idx == -1 and old_prefix_revs:
            old_active_idx = len(old_prefix_revs) - 1
            old_active_prefix = old_prefix_revs[-1].get('prefix_text', '')
        new_active_prefix = None
        for rev in reversed(new_prefix_revs):
            if rev.get('valid_to') is None:
                new_active_prefix = rev.get('prefix_text', '')
                break
        if new_active_prefix is None and new_prefix_revs:
            new_active_prefix = new_prefix_revs[-1].get('prefix_text', '')
        if old_active_prefix != new_active_prefix:
            if old_active_idx >= 0:
                old_prefix_revs[old_active_idx]['valid_to'] = valid_to_prev
            if old_active_prefix is None and new_active_prefix is not None:
                mod_type = 'add'
            elif old_active_prefix is not None and new_active_prefix is None:
                mod_type = 'delete'
            else:
                mod_type = override_mod_type if override_mod_type else 'change'
            new_rev = {
                'prefix_text': new_active_prefix if new_active_prefix is not None else '',
                'modified_by_id': modified_by_id,
                'mod_type': mod_type
            }
            if mod_type == 'add' and new_active_prefix is not None:
                new_rev['valid_from'] = change_date
            if highlights is not None and not is_highlights_empty(highlights):
                new_rev['highlights'] = highlights
            old_prefix_revs.append(new_rev)
            old_element['item_prefix_revisions'] = old_prefix_revs
            if log_callback:
                log_callback(f"  Префикс приложения изменён: '{old_active_prefix}' -> '{new_active_prefix}'", 'result')
    revisions = old_element.setdefault('revisions', [])
    # Элемент, созданный механизмом отложенного add (плейсхолдер), не является
    # настоящим изменением: его "add"-ревизия — лишь заглушка, созданная до появления
    # реального содержимого из перестройки соседнего изменения. При слиянии такого
    # плейсхолдера с реальным содержимым перестройки фантомная ревизия должна быть
    # ОТБРОШЕНА, а не закрыта + дополнена новой, иначе одно логическое изменение
    # даст две ревизии (нарушение принципа «одно изменение = одна ревизия»).
    is_placeholder_merge = bool(old_element.get('_precreated_placeholder'))
    if is_placeholder_merge:
        old_element.pop('_precreated_placeholder', None)
        placeholder_revisions = old_element.get('revisions', [])
        if placeholder_revisions:
            for rev in reversed(placeholder_revisions):
                if rev.get('valid_to') is None:
                    rev['valid_to'] = valid_to_prev
                    rev['not_valid'] = modified_by_id
                    break
        old_element['revisions'] = placeholder_revisions
    for rev in reversed(revisions):
        if rev.get('valid_to') is None:
            rev['valid_to'] = valid_to_prev
            break
    if old_element.get('_pending_mod_type') == 'add' and not revisions:
        if log_callback:
            log_callback(f"  Элемент {old_element.get('item_id')} добавлен без предварительной ревизии", 'info')
    else:
        mod_type = override_mod_type if override_mod_type is not None else 'new_redaction' if is_top_level else 'change'
        new_rev = {
            'body': new_body,
            'mod_type': mod_type,
            'modified_by_id': modified_by_id
        }
        if mod_type == 'add':
            new_rev['valid_from'] = change_date
        if highlights is not None and not is_highlights_empty(highlights):
            new_rev['highlights'] = highlights
        revisions.append(new_rev)
        if is_placeholder_merge and log_callback:
            log_callback(
                f"  Плейсхолдер-контейнер {old_element.get('item_id')} слиян с реальным "
                f"содержимым, фантомная add-ревизия отброшена; создана одна ревизия "
                f"(mod_type={mod_type})", 'result'
            )


def _ensure_path(data, tokens, valid_from, modified_by_id, log_callback, context_parent=None, ambiguous_callback=None):
    if context_parent is None:
        current_items = data.get('npa_items_revision', [])
        current_parent = None
    else:
        current_items = context_parent.get('item_children', [])
        current_parent = context_parent
    existing_ids = set()
    collect_item_ids(data, existing_ids)
    id_counter = [len(existing_ids) + 1]
    for etype, num in tokens:
        found = None
        candidates = []
        for item in current_items:
            if item.get('item_type') == etype and (num is None or match_item_type_and_number(item, etype, num)):
                    candidates.append(item)
        if len(candidates) == 1:
            found = candidates[0]
        elif len(candidates) > 1 and ambiguous_callback:
            chosen_id = ambiguous_callback(etype, num, candidates, ' '.join(str(t) for t in tokens))
            found = None if chosen_id is None else next((c for c in candidates if c.get('item_id') == chosen_id), None)
        elif len(candidates) > 0:
            raise ValueError(
                f"Неоднозначность для {etype} {num}: найдено {len(candidates)} кандидатов, "
                "но ambiguous_callback не предоставлен."
            )
        if not found and etype not in ('chapter', 'section', 'appendix', 'preamble'):
            parent_node = current_parent if current_parent else data
            if any(it.get('item_type') in ('chapter', 'section') for it in parent_node.get('item_children', [])):
                ch_candidate, inner_elem = find_element_in_chapters_or_sections(parent_node, etype, num, log_callback, ambiguous_callback)
                if ch_candidate:
                    current_parent = ch_candidate
                    current_items = ch_candidate.setdefault('item_children', [])
                    found = inner_elem
        if found:
            current_items = found.get('item_children', [])
            current_parent = found
        else:
            if log_callback:
                log_callback(f"  Создаём {etype} {num if num else ''}", 'info')
            new_item = create_element_skeleton(
                item_type=etype,
                item_number=normalize_item_number(etype, num),
                html_text='',
                parent_id=current_parent.get('item_id') if current_parent else None,
                existing_ids=existing_ids,
                id_counter=id_counter,
                item_level=(current_parent.get('item_level', 0) + 1 if current_parent else 1),
                valid_from=valid_from.strftime('%d.%m.%Y'),
                modified_by_id=modified_by_id,
                mod_type='add',
                doc_id=data.get('npa_id')
            )
            if current_parent is None:
                data['npa_items_revision'].append(new_item)
            else:
                current_parent.setdefault('item_children', []).append(new_item)
                sync_parent_body_with_children(current_parent, log_callback)
            # Помечаем элемент как плейсхолдер, созданный механизмом отложенного add
            # (родитель ещё не существовал в целевом НПА и появится только после
            # перестройки соседнего изменения). Такие контейнеры не являются настоящими
            # изменениями сами по себе — их ревизия-«add» лишь заглушка, которая при
            # слиянии в sync_structural_element_recursive должна быть отброшена,
            # чтобы не создавать двойную ревизию для одного изменения.
            new_item['_precreated_placeholder'] = True
            current_items = new_item.get('item_children', [])
            current_parent = new_item
    return current_parent

def _find_deepest_existing_ancestor(data, structural, log_callback=None):
    """Находит самый глубокий существующий предок для пути structural.

    Полезно для типа 'add', когда целевой родитель ещё не существует в целевом НПА
    (напр. 'Статья 3 часть 1'), но появится после перестройки соседнего изменения
    (new_redaction статьи 3). Возвращает (найденный_элемент, список_оставшихся_токенов).
    """
    if not structural:
        return None, []
    tokens = parse_structural_tokens(structural)
    if not tokens:
        return None, []
    current_items = data.get('npa_items_revision', [])
    current_parent = None
    consumed = 0
    for etype, num in tokens:
        found = None
        for item in current_items:
            if match_item_type_and_number(item, etype, num):
                found = item
                break
        if not found:
            break
        current_parent = found
        current_items = found.get('item_children', [])
        consumed += 1
    if consumed == 0:
        return None, tokens
    return current_parent, tokens[consumed:]

def _materialize_path(data, parent, tokens, valid_from, modified_by_id, log_callback, ambiguous_callback=None):
    """Создаёт недостающую цепочку элементов по tokens под parent.

    Возвращает (созданный_элемент_цепочки, существовал_ли_родитель).
    Используется для отложенного добавления, когда родитель появляется
    только после перестройки соседнего изменения.
    """
    return _ensure_path(
        data, tokens, valid_from, modified_by_id,
        log_callback, context_parent=parent, ambiguous_callback=ambiguous_callback
    )

def _resolve_add_parent_and_deferred(data, structural, new_str, log_callback=None, ambiguous_callback=None):
    """Разрешает родителя для add-изменения, работая с несуществующими путями.

    Для type='add' структурный элемент указывает на РОДИТЕЛЯ, в который
    добавляется новый элемент (new). Если этот путь ещё не создан в целевом НПА
    (например, 'Статья 3 часть 1' появляется только после перестройки соседнего
    new_redaction), то прямого поиска недостаточно.

    Логика:
    1. Сначала пробуем точный поиск существующего элемента по полному пути.
    2. Если найден — возвращаем (element, None): использовать как есть.
    3. Если нет — находим САМЫЙ ГЛУБОКИЙ существующий предок и возвращаем
       (ancestor, remaining_tokens), где remaining_tokens — это недостающая
       цепочка, которую нужно отложенно создать через _ensure_path.

    Возвращает (resolved_parent, deferred_tokens_or_None).
    """
    if not structural:
        return None, None
    exact = _find_existing_element_flexible(data, structural, log_callback, ambiguous_callback)
    if exact is not None:
        return exact, None
    ancestor, remaining = _find_deepest_existing_ancestor(data, structural, log_callback)
    if ancestor is None:
        return None, None
    if not remaining:
        return ancestor, None
    return ancestor, remaining

def _find_existing_element_flexible(data, structural, log_callback=None, ambiguous_callback=None):
    if not structural:
        return None
    structural.lower().strip()
    tokens = parse_structural_tokens(structural)
    if not tokens:
        return None
    candidates = []
    def _collect_candidates(items, token_idx, path_so_far=None):
        if token_idx >= len(tokens):
            return
        if path_so_far is None:
            path_so_far = []
        etype, num = tokens[token_idx]
        for item in items:
            if match_item_type_and_number(item, etype, num):
                if token_idx == len(tokens) - 1:
                    candidates.append(item)
                else:
                    _collect_candidates(item.get('item_children', []), token_idx + 1, path_so_far + [item])
            elif item.get('item_type') in ('appendix', 'structured_table', 'section', 'chapter'):
                _collect_candidates(item.get('item_children', []), token_idx, path_so_far)
    _collect_candidates(data.get('npa_items_revision', []), 0)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if ambiguous_callback:
        etype, num = tokens[-1]
        chosen_id = ambiguous_callback(etype, num, candidates, structural)
        if chosen_id is None:
            if log_callback:
                log_callback(f"  Неоднозначность для '{structural}' не разрешена, элемент не будет найден", 'warning')
            return None
        return next((c for c in candidates if c.get('item_id') == chosen_id), None)
    raise ValueError(
        f"Неоднозначность для пути '{structural}': найдено {len(candidates)} кандидатов, "
        "но ambiguous_callback не предоставлен."
    )

def find_target_chapter_or_section_for_element(parent, child_type, child_number, log_callback=None, ambiguous_callback=None):
    target_num = parse_num(str(child_number))
    best_container = None
    best_num = None
    for child in parent.get('item_children', []):
        if child.get('item_type') not in ('chapter', 'section'):
            continue
        candidates = []
        for elem in child.get('item_children', []):
            if elem.get('item_type') != child_type:
                continue
            elem_num = parse_num(elem.get('item_number', ''))
            if elem_num <= target_num:
                candidates.append((elem_num, elem))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            elem_num, elem = candidates[-1]
            if best_num is None or elem_num > best_num:
                best_num = elem_num
                best_container = child
    return best_container

def _add_new_element(parent, child_type, child_number, description, modified_by_id, valid_from, data, log_callback, rebuild_ids, ambiguous_callback=None, level_hint=None):
    normalized_number = normalize_item_number(child_type, str(child_number))
    if parent is None:
        root_items = data.get('npa_items_revision', [])
        actual_parent = None
    else:
        actual_parent = parent
    if actual_parent is not None:
        existing = find_child_by_type_and_number(actual_parent, child_type, normalized_number, ambiguous_callback)
        if existing:
            log_callback(f"  Элемент {child_type} {normalized_number} уже существует у родителя {actual_parent.get('item_id')}, добавление невозможно.", 'error')
            return None
    if child_type in ('chapter', 'section'):
        existing_opposite = any(c.get('item_type') in ('chapter', 'section') and c.get('item_type') != child_type
                                for c in (actual_parent.get('item_children', []) if actual_parent else data.get('npa_items_revision', [])))
        if existing_opposite:
            log_callback(f"  Нельзя добавить {child_type} – в родителе уже есть элементы противоположного типа (глава/раздел)", 'error')
            return None
    if parent and child_type in ('article', 'part', 'point', 'subpoint') and parent.get('item_type') != 'article':
        has_chapters_or_sections = any(c.get('item_type') in ('chapter', 'section') for c in parent.get('item_children', []))
        if has_chapters_or_sections:
            target_container = find_target_chapter_or_section_for_element(parent, child_type, child_number, log_callback, ambiguous_callback)
            if target_container:
                actual_parent = target_container
                type_name = 'главу' if target_container.get('item_type') == 'chapter' else 'раздел'
                if log_callback:
                    log_callback(f"  Добавление {child_type} {normalized_number} в {type_name} {target_container.get('item_number')}", 'info')
            else:
                containers = [c for c in parent.get('item_children', []) if c.get('item_type') in ('chapter', 'section')]
                if containers:
                    actual_parent = containers[-1]
                    type_name = 'главу' if actual_parent.get('item_type') == 'chapter' else 'раздел'
                    if log_callback:
                        log_callback(f"  Добавление {child_type} {normalized_number} в последнюю {type_name} {actual_parent.get('item_number')}", 'info')
    parent_id = actual_parent.get('item_id') if actual_parent else None
    if actual_parent:
        child_level = actual_parent.get('item_level', 0) + 1
    elif level_hint is not None:
        child_level = level_hint
    else:
        child_level = 1
    cleaned_html = clean_description_html(description)
    if not cleaned_html or not cleaned_html.strip():
        if log_callback:
            log_callback(f"  Описание для добавляемого элемента {child_type} {normalized_number} пусто после очистки", 'error')
        return None
    if child_type in ('part', 'point', 'subpoint'):
        cleaned_html = remove_leading_number_from_html(cleaned_html, str(child_number))
    parent_for_check = actual_parent if actual_parent else None
    is_table_child = parent_for_check and parent_for_check.get('item_type') == 'structured_table'
    cleaned_html = clean_and_unwrap_html(cleaned_html, is_table_child=is_table_child)
    existing_ids = set()
    collect_item_ids(data, existing_ids)
    id_counter = [len(existing_ids) + 1]
    element_skeleton = create_element_skeleton(
        item_type=child_type,
        item_number=normalized_number,
        html_text=cleaned_html,
        parent_id=parent_id,
        existing_ids=existing_ids,
        id_counter=id_counter,
        item_level=child_level,
        valid_from=None,
        modified_by_id=modified_by_id,
        mod_type='add',
        doc_id=data.get('npa_id'),
    )
    element_skeleton['_pending_new_redaction_html'] = cleaned_html
    element_skeleton['_pending_mod_type'] = 'add'
    element_skeleton['_pending_modified_by_id'] = modified_by_id
    element_skeleton['_pending_valid_from'] = valid_from.strftime('%d.%m.%Y') if valid_from else None
    if actual_parent is None:
        root_items = data.get('npa_items_revision', [])
        insert_child_in_order({'item_children': root_items}, element_skeleton, log_callback)
        data['npa_items_revision'] = root_items
    else:
        insert_child_in_order(actual_parent, element_skeleton, log_callback)
        insert_child_ref_in_body(actual_parent, element_skeleton['item_id'], log_callback)
    from npa_processor.processing.text_utils import adjust_last_item_punctuation
    adjust_last_item_punctuation(actual_parent if actual_parent else {'item_children': data.get('npa_items_revision', [])}, element_skeleton, log_callback)
    if rebuild_ids is not None and element_skeleton['item_id'] not in rebuild_ids:
        rebuild_ids.append(element_skeleton['item_id'])
    if log_callback:
        saved_number = element_skeleton.get('item_number', normalized_number)
        log_callback(f"  Добавлен новый элемент {child_type} {saved_number} (add) -> отправлен на перестройку", 'result')
    return element_skeleton['item_id']

TYPE_ORDER_PRIORITY = {
    'preamble': 0,
    'section': 1,
    'chapter': 2,
    'article': 3,
    'part': 4,
    'point': 5,
    'subpoint': 6,
    'structured_table': 7,
    'appendix': 8,
    'nested_appendix': 9,
}

def insert_child_in_order(parent, new_child, log_callback=None):
    if parent is None:
        if log_callback:
            log_callback("  insert_child_in_order: parent is None, пропуск вставки", 'warning')
        return
    children = parent.get('item_children', [])
    new_type = new_child.get('item_type', '')
    new_type_priority = TYPE_ORDER_PRIORITY.get(new_type, 10)
    num_str = new_child.get('item_number', '0')
    if not num_str:
        if log_callback:
            log_callback("  Номер элемента пуст, используется '0' для сортировки", 'warning')
        new_num = (0,)
    else:
        new_num = parse_num(str(num_str))
    insert_idx = 0
    for i, child in enumerate(children):
        child_type = child.get('item_type', '')
        child_type_priority = TYPE_ORDER_PRIORITY.get(child_type, 10)
        child_num_str = child.get('item_number', '0') or '0'
        child_num = parse_num(str(child_num_str))
        if child_type_priority < new_type_priority:
            insert_idx = i + 1
        elif child_type_priority == new_type_priority:
            if child_num <= new_num:
                insert_idx = i + 1
            else:
                break
        else:
            break
    children.insert(insert_idx, new_child)
    parent['item_children'] = children

def rebuild_element_with_history(data, element_id, valid_from, modified_by_id_str, doc_type='law', log_callback=None):
    def _log(msg, tag='info'):
        if log_callback:
            log_callback(msg, tag)
    old_item = find_item_by_id(data, element_id)
    if not old_item:
        _log(f"Элемент {element_id} не найден. Пропуск.", 'error')
        return False
    pending_html = old_item.pop('_pending_new_redaction_html', None)
    if pending_html is None:
        pending_html = old_item.pop('_pending_html', None)
    pending_mod_by = old_item.pop('_pending_modified_by_id', None)
    pending_valid_from = old_item.pop('_pending_valid_from', None)
    pending_mod_type = old_item.pop('_pending_mod_type', None)
    pending_highlights = old_item.pop('_pending_highlights', None)
    if pending_html is None:
        if old_item.get('item_children'):
            _log(f"Родитель {element_id} попал в rebuild_ids из-за добавления дочерних элементов, обновляем body", 'info')
            sync_parent_body_with_children(old_item, log_callback)
            return True
        _log(f"Элемент {element_id} не имеет pending_html и не является родителем, пропускаем перестройку", 'info')
        return True
    saved_head_revisions = copy.deepcopy(old_item.get('head_revisions', []))
    saved_prefix_revisions = copy.deepcopy(old_item.get('item_prefix_revisions', [])) if old_item.get('item_type') == 'appendix' else None
    current_html = pending_html
    effective_mod_by = pending_mod_by if pending_mod_by is not None else modified_by_id_str
    effective_valid_from = pending_valid_from if pending_valid_from else valid_from.strftime('%d.%m.%Y')
    effective_mod_type = pending_mod_type if pending_mod_type else 'change'
    effective_highlights = pending_highlights
    document_id = None
    if old_item.get('item_id') and '_' in old_item.get('item_id'):
        document_id = old_item.get('item_id').split('_', 1)[0]
    fragment_element_id = old_item.get('item_id')
    root_number = old_item.get('item_number')
    root_type = old_item.get('item_type')
    parent = find_parent(data, element_id)
    is_table_child = False
    if parent and parent.get('item_type') == 'structured_table' and old_item.get('item_type') != 'appendix':
        is_table_child = True
        old_item['_is_table_child'] = True
    TYPES_WITH_HEAD = ('article', 'chapter', 'section', 'appendix')
    if root_type in TYPES_WITH_HEAD and not is_table_child:
        current_head_text = ''
        for rev in reversed(saved_head_revisions):
            if rev.get('valid_to') in (None, ''):
                current_head_text = rev.get('head_text', '')
                break
        if not current_head_text and saved_head_revisions:
            current_head_text = saved_head_revisions[-1].get('head_text', '')
        current_prefix_text = ''
        if root_type == 'appendix' and saved_prefix_revisions:
            for rev in reversed(saved_prefix_revisions):
                if rev.get('valid_to') in (None, ''):
                    current_prefix_text = rev.get('prefix_text', '')
                    break
            if not current_prefix_text and saved_prefix_revisions:
                current_prefix_text = saved_prefix_revisions[-1].get('prefix_text', '')

        type_labels = {
            'article': 'Статья',
            'chapter': 'Глава',
            'section': 'Раздел',
            'appendix': 'Приложение',
        }
        type_label = type_labels.get(root_type, '')
        item_num = str(root_number) if root_number else ''
        header_line = None
        if root_type == 'appendix':
            if current_prefix_text:
                header_line = f"<p>{current_prefix_text}</p>"
            elif type_label and item_num:
                header_line = f"<p>{type_label} {item_num}</p>"
        elif type_label and item_num:
            if current_head_text:
                header_line = f"<p>{type_label} {item_num}. {current_head_text}</p>"
            else:
                header_line = f"<p>{type_label} {item_num}</p>"
        if header_line:
            soup_check = BeautifulSoup(current_html, 'html.parser')
            first_text = soup_check.get_text(separator=' ', strip=True)[:80].lower()
            type_label_lower = type_label.lower()
            # Ведущие кавычки (« » " ' и т.п.) могут предшествовать реальному
            # заголовку, извлечённому из кавычек источника. Отбрасываем их,
            # чтобы корректно распознать уже присутствующий заголовок и не
            # добавлять дублирующий <p>Статья N</p>.
            first_text_noquotes = first_text.lstrip('\u00ab\u00bb"\u201c\u201d\u2018\u2019\'')
            header_present = first_text_noquotes.startswith(type_label_lower) and item_num in first_text_noquotes[:30]
            if not header_present:
                current_html = header_line + '\n' + current_html
                _log(f"   Добавлен заголовок для парсера: {header_line}", 'info')
            else:
                _log("   Заголовок уже присутствует в HTML, не дублируем", 'info')
                # Если реальный заголовок в HTML начинается с ведущей кавычки
                # (напр. «Статья 5.2. Основания...»), снимаем её, иначе парсер
                # воспримет этот абзац как цитату и унесёт название/номер в body.
                if first_text != first_text_noquotes:
                    quote_soup = BeautifulSoup(current_html, 'html.parser')
                    first_block = quote_soup.find(['p', 'div'])
                    if first_block is not None:
                        first_text_node = first_block.find(string=True)
                        if first_text_node is not None:
                            node_text = str(first_text_node)
                            stripped = node_text.strip('\u00ab\u00bb"\u201c\u201d\u2018\u2019\' \t\n\r\u00a0')
                            if stripped != node_text:
                                first_text_node.replace_with(stripped)
                                current_html = str(quote_soup)
                                _log("   Снята ведущая/завершающая кавычка с заголовка для парсера", 'info')
    if root_type == 'structured_table' and not re.search(r'<table\b', current_html, re.IGNORECASE):
        current_html = f'<table border="1" cellpadding="0" cellspacing="0">{current_html}</table>'
    _log(f"Вызов NpaToJsonGenerator для {element_id} (mod_type={effective_mod_type})", 'info')
    _log(f"   pending_html длина = {len(current_html)} символов", 'debug')
    _log(f"Полный HTML:\n{current_html}", 'input')
    temp_gen = NpaToJsonGenerator(
        current_html,
        doc_type=doc_type,
        document_id=document_id,
        fragment_element_id=fragment_element_id,
        root_number=root_number,
        root_type=root_type,
        is_table_child=is_table_child
    )
    new_toc_items, ambiguous = temp_gen.generate_toc()
    if not new_toc_items:
        _log(f"Структура элемента {element_id} после пересборки пуста.", 'warning')
        return False
    new_root = new_toc_items[0]
    old_number = old_item.get('item_number', '')
    new_number = new_root.get('number', '')
    if old_number and new_number and str(old_number) != str(new_number):
        change_date_str = effective_valid_from
        if 'number_revisions' not in old_item:
            old_item['number_revisions'] = []
        for rev in old_item['number_revisions']:
            if rev.get('valid_to') is None:
                rev['valid_to'] = close_revision_date(change_date_str)
                break
        old_item['number_revisions'].append({
            'number_text': new_number,
            'valid_from': change_date_str,
            'mod_type': effective_mod_type,
            'modified_by_id': effective_mod_by
        })
        old_item['item_number'] = new_number
        if log_callback:
            log_callback(f"  Номер элемента изменён: {old_number} -> {new_number} (создана number_revision)", 'result')
    else:
        if old_number and new_number and str(old_number) == str(new_number) and log_callback:
            log_callback(f"  Номер элемента не изменился: {old_number} == {new_number}", 'info')
    if new_root.get('number'):
        num = str(new_root['number']).strip()
        if num.endswith('.') and not num.endswith('.)'):
            num = num.rstrip('.')
        old_item['item_number'] = num
    change_date_str = effective_valid_from
    if 'revisions' not in old_item:
        old_item['revisions'] = []
    sync_structural_element_recursive(
        old_item, new_root, change_date_str,
        effective_mod_by, data, log_callback, is_top_level=True,
        override_mod_type=effective_mod_type, highlights=effective_highlights,
        is_table_child=is_table_child
    )
    if not old_item.get('head_revisions'):
        if saved_head_revisions:
            old_item['head_revisions'] = saved_head_revisions
        elif new_root.get('head_revisions'):
            new_heads = new_root.get('head_revisions', [])
            for nh in new_heads:
                if nh.get('head_text') and not any(
                    r.get('head_text') == nh.get('head_text') for r in old_item.get('head_revisions', [])
                ):
                    old_item.setdefault('head_revisions', []).append(copy.deepcopy(nh))
    if old_item.get('item_type') == 'appendix' and not old_item.get('item_prefix_revisions'):
        if saved_prefix_revisions:
            old_item['item_prefix_revisions'] = saved_prefix_revisions
        elif new_root.get('item_prefix_revisions'):
            old_item['item_prefix_revisions'] = copy.deepcopy(new_root.get('item_prefix_revisions'))
    new_number_from_root = new_root.get('number') or new_root.get('item_number')
    if new_number_from_root and str(old_item.get('item_number', '')) != str(new_number_from_root):
        if 'number_revisions' not in old_item:
            old_item['number_revisions'] = []
        for rev in old_item['number_revisions']:
            if rev.get('valid_to') is None:
                rev['valid_to'] = close_revision_date(change_date_str)
                break
        mod_type_num = effective_mod_type if effective_mod_type in ('add', 'new_redaction', 'change') else 'change'
        old_item['number_revisions'].append({
            'number_text': new_number_from_root,
            'valid_from': change_date_str,
            'mod_type': mod_type_num,
            'modified_by_id': effective_mod_by
        })
        old_item['item_number'] = new_number_from_root
        if log_callback:
            log_callback(f"  [принудительно] Номер элемента изменён: -> {new_number_from_root}", 'result')
    _log(f"Результат перестройки (JSON):\n{json.dumps(old_item, ensure_ascii=False, indent=2)}", 'result')
    _log(f"Элемент {element_id} (тип {old_item.get('item_type')}, номер {old_item.get('item_number')}) перестроен через NpaToJsonGenerator (mod_type={effective_mod_type})", 'result')
    return True

def is_highlights_empty(highlights):
    if highlights is None:
        return True
    if not isinstance(highlights, dict):
        return True
    for side in ('previous_edition', 'current_edition'):
        if side in highlights:
            for cat in ('deletion', 'addition', 'difference'):
                if cat in highlights[side] and highlights[side][cat]:
                     return False
    return True

def _normalize_highlights_positions(highlights):
    if not highlights or not isinstance(highlights, dict):
        return highlights
    for side in ('previous_edition', 'current_edition'):
        if side not in highlights:
            continue
        for cat in ('deletion', 'addition', 'difference'):
            if cat not in highlights[side]:
                continue
            normalized = []
            for entry in highlights[side][cat]:
                if isinstance(entry, dict):
                    text = entry.get('text', '')
                    pos = str(entry.get('positions', '1-1'))
                elif isinstance(entry, list) and len(entry) >= 2:
                    text = entry[0]
                    pos = str(entry[1])
                else:
                    continue
                if ',' in pos:
                    for sub_pos in pos.split(','):
                        sub_pos = sub_pos.strip()
                        if '-' not in sub_pos:
                            sub_pos = f"1-{sub_pos}"
                        normalized.append([text, sub_pos])
                else:
                    if '-' not in pos:
                        pos = f"1-{pos}"
                    normalized.append([text, pos])
            highlights[side][cat] = normalized
    return highlights

def parse_add_new_field(new_str):
    if not new_str:
        return None, None
    new_str = new_str.strip()
    parts = new_str.split(maxsplit=1)
    if len(parts) != 2:
        return None, None
    ru_type = parts[0].lower()
    ru_type = normalize_ru_type(ru_type)
    number_str = parts[1].strip()
    number_str = number_str.rstrip('.)')
    number_str = number_str.strip('«»“”‘’"\'')
    number_str = number_str.rstrip('.)')
    return ru_type, number_str

def _close_revision(rev, valid_to_str):
    rev['valid_to'] = valid_to_str

def _make_new_revision(new_body, mod_type=None, modified_by_id=None, highlights=None):
    rev = {'body': new_body}
    if mod_type is not None:
        rev['mod_type'] = mod_type
    if modified_by_id is not None:
        rev['modified_by_id'] = modified_by_id
    if highlights is not None and not is_highlights_empty(highlights):
        rev['highlights'] = highlights
    return rev


def build_new_body_preserving_child_refs(old_rev, answer_html):
    old_body = sorted(old_rev.get('body', []), key=lambda b: b.get('order', 0))
    has_child_refs = any(b.get('type') == 'child_ref' for b in old_body)
    if not has_child_refs:
        paragraphs = split_html_to_paragraphs(answer_html)
        if not paragraphs:
            paragraphs = [answer_html] if answer_html.strip() else []
        return [{'type': 'paragraph', 'html_text': p, 'order': i+1} for i, p in enumerate(paragraphs)]
    new_paragraphs = split_html_to_paragraphs(answer_html)
    if not new_paragraphs:
        new_paragraphs = [answer_html] if answer_html.strip() else []
    new_body = []
    for para_idx, para in enumerate(new_paragraphs, 1):
        new_body.append({'type': 'paragraph', 'html_text': para, 'order': para_idx})
    child_refs = [b for b in old_body if b.get('type') == 'child_ref']
    for ref in child_refs:
        new_ref = dict(ref)
        new_ref['order'] = len(new_body) + 1
        new_body.append(new_ref)
    for idx, block in enumerate(new_body, 1):
        block['order'] = idx
    return new_body

def clean_number_for_filename(number):
    if not number:
        return "unknown"
    number = str(number).strip()
    if number.startswith('№'):
        number = number[1:].strip()
    number = safe_re_sub(r'[-–]\s*ЗС\s*(\d*)?$', '', number).strip()
    return number if number else "unknown"

def get_date_for_filename(data, doc_type):
    if doc_type == 'law':
        date_str = data.get('date_signed', '')
    else:
        date_str = data.get('date_passed', '')
        if not date_str:
            date_str = data.get('date_reg', '')
        if not date_str:
            date_str = data.get('date_signed', '')
    if not date_str:
        return "unknown"
    try:
        dt = None
        for fmt in ('%d.%m.%Y', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        if dt:
            return dt.strftime('%Y_%m_%d')
        else:
            return "unknown"
    except Exception:
        import logging
        logging.getLogger(__name__).debug("Failed to parse date for filename", exc_info=True)
        return "unknown"
