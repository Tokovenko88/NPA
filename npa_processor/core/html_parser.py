"""Модуль парсинга HTML-фрагментов НПА в JSON.

Содержит класс NpaToJsonGenerator для преобразования HTML-фрагментов
нормативных правовых актов в структурированный JSON.
"""

import importlib.util
import logging
import re

from bs4 import BeautifulSoup

from npa_processor._bootstrap import _bootstrap_project_root
from npa_processor.processing.text_utils import (
    normalize_number_string,
    sup_digits_to_unicode,
)

_bootstrap_project_root()


class NpaToJsonGenerator:
    def __init__(self, html_content, doc_type='law', appendix_processing_decisions=None, document_id=None, fragment_element_id=None, root_number=None, root_type=None, is_table_child=False):
        if not hasattr(self, 'logger'):
            self.logger = logging.getLogger('NpaToJsonGenerator')
            self.logger.setLevel(logging.DEBUG)
            self.logger.handlers.clear()
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            self.logger.addHandler(handler)
        html_content = sup_digits_to_unicode(html_content)
        parser = 'lxml' if importlib.util.find_spec('lxml') else 'html.parser'
        self.soup = BeautifulSoup(html_content, parser)
        self.original_html = html_content
        self.doc_type = doc_type
        self.root_number = root_number
        self.root_type = root_type
        self.document_id = document_id
        self.fragment_element_id = fragment_element_id
        self.fragment_mode = bool(fragment_element_id)
        self.is_table_child = is_table_child
        self.toc_items = []
        self.stack = []
        self.current_level = 1
        self.has_chapters_flag = False
        self.has_articles_flag = False
        self.ambiguous_elements = []
        self.collisions = []
        self.resolved_patterns = {}
        self.current_appendix_id = None
        self.in_appendix = False
        self.appendix_processing_decisions = appendix_processing_decisions or {}
        self._article_regex = re.compile(r'Статья\s+(\d+(?:\.\d+)*(?:<sup>[^>]+</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)', re.IGNORECASE)
        self._chapter_regex = re.compile(r'^\s*Глава\s+([IVXLCDM]+(?:\.\d+)?|\d+(?:\.\d+)*(?:<sup>[^>]+</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)', re.I)
        self._section_regex = re.compile(r'^\s*Раздел\s+([IVXLCDM]+(?:\.\d+)?|\d+(?:\.\d+)*(?:<sup>[^>]+</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)', re.I)
        self._appendix_regex = re.compile(r'Приложение\s+[№]?\s*(\d+(?:\.\d+)*|[IVXLCDM]+(?:\.\d+)?)', re.IGNORECASE)
        self._numbered_dot_regex = re.compile(r'^(\d+(?:\.\d+)*)\s*\.')
        self._numbered_paren_regex = re.compile(r'^(\d+(?:\.\d+)*)\s*\)')
        self._letter_paren_regex = re.compile(r'^([а-яё])\s*\)\s+', re.IGNORECASE)
        self._letter_dot_regex = re.compile(r'^([а-яё])\s*\.\s+', re.IGNORECASE)
        self._law_pattern = re.compile(r'Закон(?:ом|а)?\s+города\s+Севастополя\s+№')
        self._service_phrase_regex = re.compile(r'^принят законодательным собранием|^с изменениями, принятыми:', re.IGNORECASE)
        self._appendix_main_regex = re.compile(r'Приложение\s+[№]?\s*(\d+(?:\.\d+)*|[IVXLCDM]+(?:\.\d+)?)', re.IGNORECASE)
        self._appendix_to_doc_regex = re.compile(r'к\s+(?:Закону|Постановлению|закону|постановлению)', re.IGNORECASE)
        self._numbering_type_cache = {}
        self.skip_until_next_appendix = False
        self._inside_structured_table = False
        self._table_counter = {}
        self.used_ids = {}
        self.no_name_parents = set()
        self.errors = []
        self.all_tags = None
        self.enum_stack = []
        self._pending_enum_parent = None
        self.quote_level = 0

    def _wrap_table_html(self, html_text):
        if not html_text or '<table' not in html_text:
            return html_text
        soup = BeautifulSoup(html_text, 'html.parser')
        for table in soup.find_all('table'):
            border = table.get('border')
            if border == '1':
                parent = table.parent
                if parent and parent.name == 'div' and parent.get('class') and 'double-scroll' in parent.get('class'):
                    continue
                wrapper = soup.new_tag('div', **{'class': 'double-scroll'})
                table.wrap(wrapper)
        return str(soup)

    def _normalize_number_string(self, num_str: str) -> str:
        """Нормализует строку номера (superscript, HTML-теги) — делегирует в text_utils."""
        return normalize_number_string(num_str)

    def _get_unique_item_id(self, element_type, item_number, parent_id):
        if not item_number:
            return self.build_element_id(element_type, item_number, list(self.stack))
        key = (parent_id, element_type, str(item_number))
        count = self.used_ids.get(key, 0)
        if count == 0:
            self.used_ids[key] = 0
            base_id = self.build_element_id(element_type, item_number, list(self.stack))
            self.used_ids[key] = 1
            return base_id
        double_index = count
        self.used_ids[key] = count + 1
        base_id = self.build_element_id(element_type, item_number, list(self.stack))
        return f"{base_id}_double_{double_index}"


    def _is_structural_table_row(self, row_tag):
        cells = row_tag.find_all(['td', 'th'])
        if not cells:
            return False
        if len(cells) == 1:
            text = self.extract_text(cells[0]).strip()
            if text.lower().startswith('раздел'):
                return True
        first_cell_text = self.extract_text(cells[0]).strip()
        return bool(self._numbered_dot_regex.match(first_cell_text) or self._numbered_paren_regex.match(first_cell_text) or self._letter_paren_regex.match(first_cell_text) or self._letter_dot_regex.match(first_cell_text))

    def _parse_table_row_as_candidate(self, row_tag, row_html):
        cells = row_tag.find_all(['td', 'th'])
        if not cells:
            return None
        first_cell_text = self.extract_text(cells[0]).strip()
        search_text = first_cell_text
        if len(cells) == 1:
            m = re.match(r'^\s*Раздел\s+((?:[IVXLCDM]+[⁰¹²³⁴⁵⁶⁷⁸⁹]*)(?:\.\d+)?|\d+(?:\.\d+)?)\s*(.*)$', search_text, re.IGNORECASE)
            if m:
                number_normalized = m.group(1).upper()
                orig_match = re.match(r'^\s*Раздел\s+((?:[IVXLCDM]+[⁰¹²³⁴⁵⁶⁷⁸⁹]*)(?:[^\s]*)?)\s*(.*)$', first_cell_text, re.IGNORECASE)
                number_original = orig_match.group(1).strip() if orig_match else number_normalized
                title = orig_match.group(2).strip() if orig_match else m.group(2).strip()
                return {
                    'type': 'section',
                    'number': number_original,
                    'number_normalized': number_normalized,
                    'title': title,
                    'full_text': first_cell_text,
                    'original_html': row_html
                }
        cand = self.parse_element_candidate(first_cell_text, row_tag)
        if cand and cand['type'] in ('numbered_dot', 'numbered_paren'):
            cand['type'] = 'point' if cand.get('marker_style') in ('dot', 'paren') else 'subpoint'
            cand['original_html'] = row_html
            cand['full_text'] = first_cell_text
            return cand
        letter_match = self._letter_paren_regex.match(first_cell_text) or self._letter_dot_regex.match(first_cell_text)
        if letter_match:
            return {
                'type': 'subpoint',
                'number': letter_match.group(1),
                'title': first_cell_text[letter_match.end():].strip(),
                'full_text': first_cell_text,
                'original_html': row_html,
                'marker_style': 'paren' if ')' in first_cell_text else 'dot'
            }
        return None

    def _process_structured_table(self, table_tag, i, all_tags):
        thead_html = ''
        thead = table_tag.find('thead')
        if thead:
            thead_html = str(thead)
        tbody = table_tag.find('tbody')
        rows = tbody.find_all('tr') if tbody else table_tag.find_all('tr')
        if not rows:
            return False

        nonstructural_prefix = []
        groups = []
        current_group = None
        for row in rows:
            row_html = str(row)
            cand = self._parse_table_row_as_candidate(row, row_html)
            if cand:
                if nonstructural_prefix and not groups:
                    groups.insert(0, {'type': 'nonstructural', 'rows_html': nonstructural_prefix})
                    nonstructural_prefix = []
                if current_group:
                    groups.append(current_group)
                current_group = {
                    'type': cand['type'],
                    'number': cand.get('number', ''),
                    'number_normalized': cand.get('number_normalized', cand.get('number', '')),
                    'title': cand.get('title', ''),
                    'rows_html': [row_html],
                    'level': 1
                }
            else:
                if current_group:
                    current_group['rows_html'].append(row_html)
                else:
                    nonstructural_prefix.append(row_html)
        if current_group:
            groups.append(current_group)
        if nonstructural_prefix and not groups:
            groups.insert(0, {'type': 'nonstructural', 'rows_html': nonstructural_prefix})
        if not groups:
            return False

        root_items = []
        stack = []
        nonstructural_parts = []
        for grp in groups:
            if grp['type'] == 'nonstructural':
                nonstructural_parts.extend(grp['rows_html'])
                continue
            if grp['type'] == 'section':
                level = 1
            elif grp['type'] == 'point':
                level = 2 if any(item['type'] == 'section' for item in stack) else 1
            else:
                level = len(stack) + 1
            while len(stack) >= level:
                stack.pop()
            item = {
                'type': grp['type'],
                'number': grp['number'],
                'number_normalized': grp.get('number_normalized', grp['number']),
                'title': grp['title'],
                'original_html': ''.join(grp['rows_html']),
                'children': [],
                'level': level
            }
            if stack:
                stack[-1]['children'].append(item)
            else:
                root_items.append(item)
            stack.append(item)

        if root_items is None:
            root_items = []
        parent_element = self.stack[-1] if self.stack else None

        is_fragment_rebuild = (
            self.fragment_mode
            and parent_element is not None
            and parent_element.get('is_fragment_target', False)
            and (
                parent_element.get('type') == 'structured_table'
                or self.root_type == 'structured_table'
            )
        )

        if is_fragment_rebuild:
            structured_item = parent_element
            structured_item['type'] = 'structured_table'
            structured_item['children'] = []
            structured_item['thead_html'] = thead_html
            structured_item['_nonstructural_prefix'] = nonstructural_parts

            for child_item in root_items:
                self._add_structured_table_child(child_item, structured_item)

            body_blocks = []
            order = 1
            if thead_html:
                body_blocks.append({'type': 'table_header', 'html_text': thead_html, 'order': order})
                order += 1
            for part_html in nonstructural_parts:
                body_blocks.append({'type': 'paragraph', 'html_text': part_html, 'order': order})
                order += 1
            for child in structured_item.get('children', []):
                body_blocks.append({'type': 'child_ref', 'item_id': child['id'], 'order': order})
                order += 1

            structured_item['revisions'] = [{'body': body_blocks}]
            return True

        parent_key = id(self.stack[-1]) if self.stack else 'root'
        self._table_counter[parent_key] = self._table_counter.get(parent_key, 0) + 1
        table_number = self._table_counter[parent_key]
        parent_id = parent_element['id'] if parent_element else None
        table_id = self._get_unique_item_id('structured_table', str(table_number), parent_id)
        structured_item = {
            'id': table_id,
            'type': 'structured_table',
            'number': str(table_number),
            'title': '',
            'full_text': '',
            'original_html': str(table_tag),
            'children': [],
            'level': (parent_element['level'] + 1) if parent_element else 1,
            'thead_html': thead_html,
            'parent_id': parent_element['id'] if parent_element else None,
            'collected_content': [],
            'head_revisions': [],
            '_nonstructural_prefix': nonstructural_parts
        }
        if parent_element:
            parent_element.setdefault('children', []).append(structured_item)
        self.stack.append(structured_item)
        self._inside_structured_table = True
        if root_items:
            for child_item in root_items:
                self._add_structured_table_child(child_item, structured_item)
        body_blocks = []
        order = 1
        if thead_html:
            body_blocks.append({'type': 'table_header', 'html_text': thead_html, 'order': order})
            order += 1
        for part_html in nonstructural_parts:
            soup_part = BeautifulSoup(part_html, 'html.parser')
            if soup_part.find('td') or soup_part.find('th'):
                body_blocks.append({'type': 'paragraph', 'html_text': part_html, 'order': order})
                order += 1
        for child in structured_item.get('children', []):
            body_blocks.append({'type': 'child_ref', 'item_id': child['id'], 'order': order})
            order += 1
        if body_blocks:
            if 'revisions' not in structured_item:
                structured_item['revisions'] = [{'body': []}]
            structured_item['revisions'][0]['body'] = body_blocks
        self._inside_structured_table = False
        return True

    def _add_structured_table_child(self, child_item, parent_item):
        elem_type = child_item['type']
        number = child_item['number']
        level = parent_item['level'] + 1
        anchor = self._get_unique_item_id(elem_type, number, parent_item['id'])
        display_text = self.get_display_text(elem_type, number, child_item, child_item.get('title', ''))
        new_item = {
            'id': anchor,
            'type': elem_type,
            'number': number,
            'display_text': display_text,
            'full_text': child_item.get('title', ''),
            'title': child_item.get('title', ''),
            'level': level,
            'children': [],
            'parent_id': parent_item['id'],
            'original_html': child_item['original_html'],
            'collected_content': [],
            'head_revisions': [{'head_text': child_item.get('title', '')}] if child_item.get('title') else [],
            'revisions': [{'body': [{'type': 'table_fragment', 'html_text': child_item['original_html'], 'order': 1}]}],
            '_is_table_child': True
        }
        parent_item.setdefault('children', []).append(new_item)
        self.stack.append(new_item)
        for grandchild in child_item.get('children', []):
            self._add_structured_table_child(grandchild, new_item)
        self.stack.pop()

    def _process_table(self, tag, i, all_tags):
        is_nonstructural = False
        if tag.get('border') == '0':
            is_nonstructural = True
        else:
            rows = tag.find_all('tr')
            found_structural = False
            for row in rows[:20]:
                if self._is_structural_table_row(row):
                    found_structural = True
                    break
            if not found_structural:
                is_nonstructural = True

        if is_nonstructural:
            if self.stack:
                self.stack[-1].setdefault('collected_content', []).append(str(tag))
            else:
                anchor = self.build_element_id('orphan')
                item = {
                    'id': anchor,
                    'type': 'paragraph',
                    'number': '',
                    'display_text': '',
                    'full_text': '',
                    'title': '',
                    'level': 1,
                    'children': [],
                    'parent_id': None,
                    'collected_content': [str(tag)],
                    'head_revisions': []
                }
                self.toc_items.append(item)
                self.stack.append(item)

            if self.quote_level > 0:
                self.logger.info(f"Сброс quote_level={self.quote_level} после неструктурной таблицы")
                self.quote_level = 0
                self._pending_enum_parent = None
                self.pending_parent_for_next_content = None
            return True

        self._process_structured_table(tag, i, all_tags)
        return True


    def _parse_table_row_candidate(self, tr_tag):
        cells = tr_tag.find_all(['td', 'th'])
        if not cells:
            return None
        first_cell = cells[0]
        colspan = first_cell.get('colspan')
        if colspan and int(colspan) > 1:
            text = first_cell.get_text(strip=True)
            sect_match = self._section_regex.match(text)
            if sect_match:
                return {
                    'type': 'section',
                    'number': sect_match.group(1),
                    'title': text,
                    'full_text': text,
                    'original_html': str(tr_tag)
                }
            if text.lower().startswith('раздел') or text.lower().startswith('глава'):
                cleaned_num = text.split('.')[0].replace('Раздел', '').replace('Глава', '').strip()
                return {
                    'type': 'section',
                    'number': cleaned_num,
                    'title': text,
                    'full_text': text,
                    'original_html': str(tr_tag)
                }
        cell_texts = [c.get_text(strip=True) for c in cells if c.get_text(strip=True)]
        if not cell_texts:
            return None
        first_text = cell_texts[0]
        dot_match = self._numbered_dot_regex.match(first_text)
        paren_match = self._numbered_paren_regex.match(first_text)
        if dot_match:
            num = dot_match.group(1)
            rest = first_text[dot_match.end():].strip()
            title = rest if rest else (cell_texts[1] if len(cell_texts) > 1 else '')
            return {
                'type': 'point',
                'number': num,
                'title': title,
                'full_text': " ".join(cell_texts),
                'original_html': str(tr_tag)
            }
        if paren_match:
            num = paren_match.group(1)
            rest = first_text[paren_match.end():].strip()
            title = rest if rest else (cell_texts[1] if len(cell_texts) > 1 else '')
            return {
                'type': 'point',
                'number': num,
                'title': title,
                'full_text': " ".join(cell_texts),
                'original_html': str(tr_tag)
            }
        letter_paren = self._letter_paren_regex.match(first_text)
        letter_dot = self._letter_dot_regex.match(first_text)
        if letter_paren:
            num = letter_paren.group(1)
            rest = first_text[letter_paren.end():].strip()
            title = rest if rest else (cell_texts[1] if len(cell_texts) > 1 else '')
            return {
                'type': 'subpoint',
                'number': num,
                'title': title,
                'full_text': " ".join(cell_texts),
                'original_html': str(tr_tag)
            }
        if letter_dot:
            num = letter_dot.group(1)
            rest = first_text[letter_dot.end():].strip()
            title = rest if rest else (cell_texts[1] if len(cell_texts) > 1 else '')
            return {
                'type': 'subpoint',
                'number': num,
                'title': title,
                'full_text': " ".join(cell_texts),
                'original_html': str(tr_tag)
            }
        return None

    def _para_quote_state(self, text):
        if not text:
            return 0, 0, 0, False, False
        opens = text.count('«')
        closes = text.count('»')
        net = opens - closes
        starts_with_open = text.lstrip().startswith('«')
        legal_close = bool(re.search(r'»(?:[.;,])?$', text.rstrip()))
        return opens, closes, net, starts_with_open, legal_close


    def _open_enumeration(self, parent_item, candidate):
        full_text = candidate.get('full_text', '')
        close_on_dot = full_text.rstrip().endswith(';')
        level_info = {
            'parent_item': parent_item,
            'close_on_dot': close_on_dot,
            'marker_style': candidate.get('marker_style', ''),
            'level': len(self.enum_stack) + 1
        }
        self.enum_stack.append(level_info)

    def _close_enumeration(self):
        if not self.enum_stack:
            return
        closed = self.enum_stack.pop()
        self.pending_parent_for_next_content = closed['parent_item']


    def _sync_enum_stack(self):
        if not self.enum_stack:
            return
        stack_ids = {item['id'] for item in self.stack}
        new_stack = []
        for level in self.enum_stack:
            if level['parent_item']['id'] in stack_ids:
                new_stack.append(level)
        self.enum_stack = new_stack
