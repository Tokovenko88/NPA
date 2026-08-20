"""Модуль парсинга HTML-фрагментов НПА в JSON.

Содержит класс NpaToJsonGenerator для преобразования HTML-фрагментов
нормативных правовых актов в структурированный JSON.
"""

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
        self.log_queue = None
        html_content = sup_digits_to_unicode(html_content)
        try:
            import lxml
            self.soup = BeautifulSoup(html_content, 'lxml')
        except ImportError:
            self.soup = BeautifulSoup(html_content, 'html.parser')
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


    def _filter_out_table_children(self, tags):
        if tags is None:
            return []
        filtered = []
        for tag in tags:
            if tag.name == 'table':
                parent_div = tag.find_parent('div')
                if parent_div and parent_div.get('class') and 'double-scroll' in parent_div.get('class'):
                    continue
                filtered.append(tag)
            elif tag.find_parent('table') is None:
                filtered.append(tag)
        return filtered

    def _is_starting_number(self, number_str):
        num = str(number_str).strip().lower()
        return num == '1' or num == 'а'

    def _close_enumeration_if_needed(self):
        if not self.enum_stack:
            return False
        if not self.stack:
            return False
        last_item = self.stack[-1]
        full_text = last_item.get('full_text', '')
        if full_text.rstrip().endswith('.') and self.enum_stack[-1]['close_on_dot']:
            self._close_enumeration()
            return True
        return False

    def parse_element_path_from_id(self, element_id: str):
        if not element_id or '_' not in element_id:
            return []
        parts = element_id.split('_')
        parts = parts[1:]
        type_patterns = [
            ('structured_table', ['structured', 'table']),
            ('nested_appendix', ['nested', 'appendix']),
            ('appendix', ['appendix']),
            ('chapter', ['chapter']),
            ('section', ['section']),
            ('article', ['article']),
            ('part', ['part']),
            ('point', ['point']),
            ('subpoint', ['subpoint']),
            ('preamble', ['preamble']),
        ]

        def match_type_at(idx):
            for type_name, type_parts in type_patterns:
                if parts[idx:idx + len(type_parts)] == type_parts:
                    return type_name, len(type_parts)
            return None, 0

        path = []
        i = 0
        while i < len(parts):
            type_name, consumed = match_type_at(i)
            if type_name is None:
                i += 1
                continue
            i += consumed
            number_parts = []
            while i < len(parts):
                next_type, _ = match_type_at(i)
                if next_type is not None:
                    break
                if parts[i] == 'double':
                    i += 1
                    if i < len(parts):
                        i += 1
                    continue
                number_parts.append(parts[i])
                i += 1
            number = '.'.join(number_parts) if number_parts else ''
            path.append((type_name, number))
        return path

    def _log_stack_state(self, context):
        if not hasattr(self, 'log_queue') or not self.log_queue:
            return
        stack_info = []
        for idx, item in enumerate(self.stack):
            stack_info.append(f"  {idx+1}. {item['type']} #{item.get('number', '')} (уровень {item['level']})")
        stack_str = "\n".join(stack_info) if stack_info else "  (пусто)"
        msg = f"СТЕК НА МОМЕНТ {context}:\n{stack_str}"
        self.log_queue.put(('log', msg, 'INFO'))

    def reconstruct_initial_stack(self, element_id: str):
        path = self.parse_element_path_from_id(element_id)
        if not path:
            self.stack = []
            return
        self.stack = []
        for idx, (elem_type, number) in enumerate(path):
            parent_items = list(self.stack)

            if idx == len(path) - 1 and self.root_type is not None:
                elem_type = self.root_type

            anchor = self.build_element_id(elem_type, number, parent_items)
            item = {
                'id': anchor,
                'type': elem_type,
                'number': number,
                'display_text': self.get_display_text(elem_type, number, '', ''),
                'full_text': '',
                'title': '',
                'level': idx + 1,
                'children': [],
                'parent_id': self.stack[-1]['id'] if self.stack else None,
                'collected_content': [],
                'post_children_content': [],
                'dot_count': number.count('.') if '.' in number else 0,
                'marker_style': '',
                'is_main_appendix': False,
                'is_nested_appendix': False,
                'is_fragment_target': (idx == len(path) - 1)
            }
            if idx == len(path) - 1 and self.root_number is not None:
                item['number'] = self.root_number
                item['dot_count'] = self.root_number.count('.') if '.' in self.root_number else 0
                item['display_text'] = self.get_display_text(elem_type, self.root_number, '', '')
            self.stack.append(item)
        if self.stack:
            self.toc_items = [self.stack[0]]
            for i in range(1, len(self.stack)):
                parent = self.stack[i - 1]
                child = self.stack[i]
                parent.setdefault('children', []).append(child)

    def process_fragment(self, fragment_html: str, element_id: str):
        self.logger.info(f"ФРАГМЕНТ: start processing id={element_id}, html_len={len(fragment_html)}")
        self.used_ids.clear()
        self.reconstruct_initial_stack(element_id)
        if not self.stack:
            self.logger.error("ФРАГМЕНТ: стек пуст после восстановления")
            return None
        self.fragment_target = self.stack[-1]
        self.fragment_target_item = self.fragment_target

        if self.is_table_child:
            self.logger.info("ФРАГМЕНТ: is_table_child=True, извлекаем номер и заголовок из HTML")
            soup = BeautifulSoup(fragment_html, 'html.parser')
            p_tags = soup.find_all('p', align='center')
            number_raw = None
            title_text = None
            for p in p_tags:
                p_html = str(p)
                match = re.search(r'Раздел\s+((?:[IVXLCDM]+(?:<sup>\d+</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?))', p_html, re.IGNORECASE)
                if match:
                    number_raw = match.group(1).strip()
                    number_raw = self.sup_digits_to_unicode(number_raw)
                    break
                else:
                    text = p.get_text()
                    match_text = re.search(r'Раздел\s+([IVXLCDM]+(?:[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)', text, re.IGNORECASE)
                    if match_text:
                        number_raw = match_text.group(1).strip()
                        break
                if not title_text and p.get_text(strip=True):
                    title_text = p.get_text(strip=True)
            if number_raw:
                self.fragment_target['number'] = number_raw
            if title_text:
                self.fragment_target['head_revisions'] = [{'head_text': title_text}]
                self.fragment_target['title'] = title_text
            if not self.fragment_target.get('collected_content'):
                self.fragment_target['collected_content'] = [fragment_html]
            body = [{'type': 'table_fragment', 'html_text': fragment_html, 'order': 1}]
            self.fragment_target['revisions'] = [{'body': body}]
            self.fragment_target['_is_table_child'] = True
            converted_items, _ = self.convert_to_new_format([self.fragment_target], 1)
            if converted_items:
                self.logger.info("ФРАГМЕНТ: табличный фрагмент сохранён успешно")
            return converted_items[0] if converted_items else None

        try:
            import lxml
            self.soup = BeautifulSoup(fragment_html, 'lxml')
        except ImportError:
            self.soup = BeautifulSoup(fragment_html, 'html.parser')
        raw_tags = self.soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'table'])
        all_tags = self._filter_out_table_children(raw_tags)
        if not all_tags:
            if self.soup.body:
                all_tags = list(self.soup.body.children)
            else:
                all_tags = list(self.soup.children)
            all_tags = [tag for tag in all_tags if hasattr(tag, 'name')]

        self.quote_level = 0
        self.enum_stack = []
        self.pending_parent_for_next_content = None
        self._pending_enum_parent = None
        self.fragment_content_started = False

        last_was_structural_word = False
        i = 0
        while i < len(all_tags):
            tag = all_tags[i]
            if not hasattr(tag, 'name'):
                i += 1
                continue
            if tag.name == 'div' and tag.get('class') and 'double-scroll' in tag.get('class'):
                table_inside = tag.find('table')
                if table_inside:
                    table_inside.extract()
                    tag.decompose()
                    tag = table_inside
                else:
                    i += 1
                    continue
            if tag.name == 'table':
                saved_quote_level = self.quote_level
                self.quote_level = 0
                self._process_table(tag, i, all_tags)
                if saved_quote_level > 0:
                    self.quote_level = saved_quote_level
                i += 1
                continue

            text = self.extract_text(tag).strip()
            has_img = tag.find('img') is not None
            has_content = bool(text) or has_img or bool(tag.find_all(['img', 'table', 'figure']))
            if not has_content:
                i += 1
                continue

            if has_img:
                if self.stack:
                    self.stack[-1].setdefault('collected_content', []).append(str(tag))
                i += 1
                continue

            open_quotes = text.count('«')
            close_quotes = text.count('»')
            old_quote_level = self.quote_level
            self.quote_level += open_quotes - close_quotes
            if self.quote_level < 0:
                self.quote_level = 0
            if old_quote_level > 0 or self.quote_level > 0:
                self._process_nonstructural_tag_with_enumeration(tag, text, force_nonstructural=True)
                i += 1
                continue

            candidate = self.parse_element_candidate(text, tag)
            if candidate:
                is_structural_word = candidate['type'] in ('article', 'chapter', 'section', 'appendix', 'nested_appendix')
                if is_structural_word and last_was_structural_word:
                    self._process_nonstructural_tag_with_enumeration(tag, text, force_nonstructural=True)
                    last_was_structural_word = False
                else:
                    if not self.fragment_content_started:
                        target_number = self.fragment_target.get('number', '')
                        candidate_full_number = f"{candidate.get('number', '')}{candidate.get('suffix', '')}"
                        if candidate_full_number == target_number or candidate.get('number', '') == target_number:
                            new_head = None
                            collected_extra = False
                            if candidate.get('type') == 'article' and candidate.get('title'):
                                new_head = candidate['title']
                            elif candidate.get('type') == 'chapter' and candidate.get('title'):
                                new_head = candidate['title']
                            elif candidate.get('type') == 'section' and candidate.get('title'):
                                new_head = candidate['title']
                            elif candidate.get('type') == 'appendix':
                                title, skip, title_tags = self.find_appendix_title(all_tags, i + 1)
                                if title:
                                    has_title = self._ask_user_appendix_title(title)
                                    if has_title:
                                        new_head = title
                                        i += skip
                                    else:
                                        for t_tag in title_tags:
                                            self.fragment_target.setdefault('collected_content', []).append(str(t_tag))
                                        collected_extra = True
                                        i += skip
                                else:
                                    collected_extra = True

                                if candidate.get('prefix'):
                                    prefix_rev = [{'prefix_text': candidate['prefix']}]
                                    self.fragment_target['item_prefix_revisions'] = prefix_rev

                            if new_head is not None:
                                self.fragment_target['title'] = new_head
                                self.fragment_target['head_revisions'] = [{'head_text': new_head}]
                                if 'collected_content' in self.fragment_target:
                                    del self.fragment_target['collected_content']
                            elif candidate.get('type') in ('article', 'chapter', 'section'):
                                pass
                            elif not collected_extra:
                                self.fragment_target.setdefault('collected_content', []).append(str(tag))

                            self.fragment_target['full_text'] = candidate.get('full_text', '')
                            self.fragment_target['original_html'] = candidate.get('original_html', '')
                            self.fragment_content_started = True
                            ends_with_colon = text.rstrip().endswith(':')
                            if ends_with_colon:
                                self._pending_enum_parent = self.fragment_target_item
                            i += 1
                            continue
                        else:
                            self._process_structural_candidate_with_enumeration(candidate)
                            self.fragment_content_started = True
                    else:
                        self._process_structural_candidate_with_enumeration(candidate)
                    last_was_structural_word = is_structural_word
            else:
                if not self.fragment_content_started:
                    self.fragment_target.setdefault('collected_content', []).append(str(tag))
                    self.fragment_content_started = True
                    if text.rstrip().endswith(':'):
                        self._pending_enum_parent = self.fragment_target_item
                else:
                    self._process_nonstructural_tag_with_enumeration(tag, text)
                last_was_structural_word = False

            i += 1

        actual_target = self.fragment_target_item if hasattr(self, 'fragment_target_item') and self.fragment_target_item else self.stack[-1] if self.stack else None
        if actual_target:
            if self.is_table_child:
                full_html = ''.join(actual_target.get('collected_content', []))
                if not full_html and actual_target.get('original_html'):
                    full_html = actual_target['original_html']
                body = [{'type': 'table_fragment', 'html_text': full_html, 'order': 1}]
                actual_target['revisions'] = [{'body': body}]
                actual_target['_is_table_child'] = True
            converted_items, _ = self.convert_to_new_format([actual_target], 1)
            return converted_items[0] if converted_items else None
        return None

    def create_pattern_hash(self, candidate, parent_type=None):
        if not isinstance(candidate, dict):
            candidate_str = str(candidate)
            pattern_key = f"{parent_type}_error_{candidate_str}"
            return pattern_key
        candidate_str = str(candidate)
        pattern_key = f"{parent_type}_error_{candidate_str}"
        return pattern_key

    def determine_numbering_type(self, candidate):
        if not isinstance(candidate, dict):
            return None
        cache_key = f"{candidate.get('number', '')}_{candidate.get('marker_style', '')}"
        if cache_key in self._numbering_type_cache:
            return self._numbering_type_cache[cache_key]
        number = str(candidate.get('number', ''))
        marker_style = candidate.get('marker_style', '')
        if not number:
            self._numbering_type_cache[cache_key] = None
            return None
        clean_number = number.rstrip(').').strip()
        if re.match(r'^\d+(\.\d+)*$', number) and marker_style == 'dot':
            self._numbering_type_cache[cache_key] = 'type1'
            return 'type1'
        elif re.match(r'^\d+(\.\d+)*$', number) and marker_style == 'paren':
            self._numbering_type_cache[cache_key] = 'type2'
            return 'type2'
        elif re.match(r'^[а-я]$', clean_number.lower()) and marker_style == 'dot':
            self._numbering_type_cache[cache_key] = 'type3'
            return 'type3'
        elif re.match(r'^[а-я]$', clean_number.lower()) and marker_style == 'paren':
            self._numbering_type_cache[cache_key] = 'type4'
            return 'type4'
        elif '.' in number:
            base_number = number.split('.')[0]
            base_candidate = candidate.copy()
            base_candidate['number'] = base_number
            base_candidate['marker_style'] = marker_style
            base_type = self.determine_numbering_type(base_candidate)
            if base_type:
                extended_type = f"{base_type}_extended"
                self._numbering_type_cache[cache_key] = extended_type
                return extended_type
        self._numbering_type_cache[cache_key] = None
        return None

    def is_same_numbering_type(self, candidate1, candidate2):
        type1 = self.determine_numbering_type(candidate1)
        type2 = self.determine_numbering_type(candidate2)
        if not type1 or not type2:
            return False
        clean_type1 = type1.replace('_extended', '')
        clean_type2 = type2.replace('_extended', '')
        if clean_type1 == 'type2' and clean_type2 == 'type2':
            return True
        return clean_type1 == clean_type2 and type1.endswith('_extended') == type2.endswith('_extended')

    def is_extension_of(self, parent_candidate, child_candidate):
        if not isinstance(parent_candidate, dict) or not isinstance(child_candidate, dict):
            return False
        parent_number = str(parent_candidate.get('number', ''))
        child_number = str(child_candidate.get('number', ''))
        if child_number.startswith(parent_number + '.'):
            remaining = child_number[len(parent_number) + 1:]
            if re.match(r'^\d+$', remaining) or re.match(r'^[а-я]$', remaining.lower()):
                parent_dots = parent_candidate.get('dot_count', 0)
                child_dots = child_candidate.get('dot_count', 0)
                child_marker = child_candidate.get('marker_style', '')
                if child_marker == 'dot':
                    return child_dots > parent_dots and child_dots > 1
                else:
                    return child_dots > parent_dots
        return False

    def is_extended_element(self, candidate):
        if not isinstance(candidate, dict):
            return False
        number = str(candidate.get('number', ''))
        marker_style = candidate.get('marker_style', '')
        if '.' not in number:
            return False
        if marker_style == 'dot':
            dot_count = candidate.get('dot_count', 0)
            return dot_count > 1
        else:
            dot_count = candidate.get('dot_count', 0)
            return dot_count >= 1

    def fix_split_roman_numbers(self, text):
        roman_patterns = [
            (r'I\s+V', 'IV'),
            (r'I\s+X', 'IX'),
            (r'V\s+I', 'VI'),
            (r'V\s+I\s+I', 'VII'),
            (r'V\s+I\s+I\s+I', 'VIII'),
            (r'X\s+I', 'XI'),
            (r'X\s+I\s+I', 'XII'),
            (r'X\s+I\s+V', 'XIV'),
            (r'X\s+V', 'XV'),
            (r'X\s+X', 'XX'),
            (r'([IVXLCDM]+)\s*\.\s*(\d+)', r'\1.\2'),
            (r'([IVXLCDM]+)\s*\.', r'\1.'),
        ]
        for pattern, replacement in roman_patterns:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def normalize_roman_number(self, roman_str):
        if not roman_str:
            return roman_str
        if '.' in roman_str:
            parts = roman_str.split('.')
            if len(parts) == 2:
                roman_part = parts[0]
                arabic_part = parts[1]
                roman_pattern = re.compile(r'^[IVXLCDM]+$', re.I)
                if roman_pattern.match(roman_part.upper()):
                    normalized_roman = re.sub(r'\s*\.\s*', '.', roman_part.upper())
                    normalized_roman = re.sub(r'[-\s]+', '', normalized_roman)
                    return f"{normalized_roman}.{arabic_part}"
        roman_pattern = re.compile(r'^[IVXLCDM]+(?:\.\d+)*$', re.I)
        if roman_pattern.match(roman_str.upper()):
            normalized = re.sub(r'\s*\.\s*', '.', roman_str.upper())
            normalized = re.sub(r'[-\s]+', '', normalized)
            return normalized
        return roman_str

    def extract_text(self, element):
        if isinstance(element, str):
            return element
        if hasattr(element, 'name') and element.name in ['sup', 'sub']:
            return element.get_text(strip=True)
        if hasattr(element, 'name') and element.name == 'br':
            return ' '
        if hasattr(element, 'children'):
            parts = []
            for child in element.children:
                if isinstance(child, str):
                    parts.append(child)
                else:
                    parts.append(self.extract_text(child))
            text = ' '.join(parts)
            text = re.sub(r'(\d+)\s+(\d+)', r'\1\2', text)
        else:
            text = element.get_text(separator=' ', strip=True) if hasattr(element, 'get_text') else str(element)
        text = text.replace('&laquo;', '«').replace('&raquo;', '»')
        text = text.replace('\xa0', ' ').replace('&nbsp;', ' ')
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'(\d+)\s*\.\s*(\d+)', r'\1.\2', text)
        text = text.strip()
        return text

    def clean_text(self, text):
        if not text:
            return ""
        text = text.replace('\xa0', ' ')
        text = text.replace('\u2009', ' ')
        text = text.replace('\u202f', ' ')
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&laquo;', '«').replace('&raquo;', '»')
        text = text.replace('\r\n', ' ')
        text = text.replace('\n', ' ')
        text = re.sub(r'\s*\.\s*', '.', text)
        text = re.sub(r'(\d+)\s*\)', r'\1)', text)
        text = self.fix_split_roman_numbers(text)
        text = re.sub(r'Глава\s+', 'Глава ', text, flags=re.IGNORECASE)
        text = ' '.join(text.split())
        return text.strip()

    def build_element_id(self, element_type, number=None, parent_items=None):
        prefix = str(self.document_id) if self.document_id is not None else 'toc'
        parts = [prefix]
        if parent_items:
            for parent in parent_items:
                p_type = parent.get('type', '')
                p_num = str(parent.get('number', ''))
                p_num_clean = re.sub(r'[.)]$', '', p_num).replace('.', '_')
                if p_type == 'preamble':
                    parts.append('preamble')
                elif p_num_clean:
                    parts.append(f"{p_type}_{p_num_clean}")
                else:
                    parts.append(p_type)
        if element_type == 'preamble':
            parts.append('preamble')
        elif element_type == 'structured_table':
            num_str = str(number) if number else ''
            num_clean = re.sub(r'[.)]$', '', num_str).replace('.', '_')
            if num_clean:
                parts.append(f"structured_table_{num_clean}")
            else:
                parts.append('structured_table')
        else:
            num_str = str(number) if number else ''
            num_clean = re.sub(r'[.)]$', '', num_str).replace('.', '_')
            if num_clean:
                parts.append(f"{element_type}_{num_clean}")
            else:
                parts.append(element_type)
        return '_'.join(parts)

    def get_display_text(self, element_type, number, full_text, title=""):
        if element_type == 'preamble':
            return "Преамбула"
        elif element_type == 'appendix':
            if number:
                base = f"Приложение {number}"
            else:
                base = "Приложение"
            if title:
                return f"{base}. {title}"
            return base
        elif element_type == 'nested_appendix':
            if number:
                base = f"Приложение {number}"
            else:
                base = "Приложение"
            if title:
                return f"{base}. {title}"
            return base
        elif element_type == 'chapter':
            if isinstance(number, str):
                if re.match(r'^[IVXLCDM]+(?:\.\d+)*$', number.upper()):
                    number = self.normalize_roman_number(number)
                elif re.match(r'^\d+(\.\d+)*$', number):
                    pass
            if number and number.endswith('.'):
                number = number.rstrip('.')
            base = f"Глава {number}"
            if title:
                if not base.endswith('.'):
                    base = base + '.'
                return f"{base} {title}"
            return base
        elif element_type == 'section':
            if isinstance(number, str):
                if re.match(r'^[IVXLCDM]+(?:\.\d+)*$', number.upper()):
                    number = self.normalize_roman_number(number)
                elif re.match(r'^\d+(\.\d+)*$', number):
                    pass
            if number and number.endswith('.'):
                number = number.rstrip('.')
            base = f"Раздел {number}"
            if title:
                if not base.endswith('.'):
                    base = base + '.'
                return f"{base} {title}"
            return base
        elif element_type == 'article':
            base = f"Статья {number}"
            if title:
                if re.match(r'^\d+$', title.strip()):
                    if '.' not in str(number):
                        return f"Статья {number}.{title}"
                return f"{base}. {title}"
            return base
        elif element_type == 'part':
            base = f"Часть {number}"
            if full_text and isinstance(full_text, dict):
                marker_style = full_text.get('marker_style', '')
                if marker_style == 'dot' and not str(number).endswith('.'):
                    base = f"{base}."
            if title:
                return f"{base}. {title}"
            return base
        elif element_type == 'point':
            base = f"Пункт {number}"
            if full_text and isinstance(full_text, dict):
                marker_style = full_text.get('marker_style', '')
                if marker_style == 'dot' and not str(number).endswith('.'):
                    base = f"{base}."
                elif marker_style == 'paren' and not str(number).endswith(')'):
                    base = f"{base})"
            if title:
                return f"{base}. {title}"
            return base
        elif element_type == 'subpoint':
            base = f"Подпункт {number}"
            if full_text and isinstance(full_text, dict):
                marker_style = full_text.get('marker_style', '')
                if marker_style == 'dot' and not str(number).endswith('.'):
                    base = f"{base}."
                elif marker_style == 'paren' and not str(number).endswith(')'):
                    base = f"{base})"
            if title:
                return f"{base}. {title}"
            return base
        return full_text[:50] if isinstance(full_text, str) else str(full_text)

    def parse_element_candidate(self, text, tag):
        original_text = text
        cleaned_text = self.clean_text(original_text)
        cleaned_text = self._normalize_number_string(cleaned_text)
        original_html = str(tag)
        if re.match(r'^\s*И\.\s*о\.', cleaned_text, re.IGNORECASE):
            return None

        article_match = re.match(r'^Статья\s+(\d+(?:\.\d+)*(?:<sup>[^>]+</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)\s*\.?\s*(.*)$', cleaned_text, re.IGNORECASE)
        if article_match:
            number = self._normalize_number_string(article_match.group(1))
            title = article_match.group(2).strip()
            if not title:
                after_number = re.split(r'^Статья\s+\d+(?:\.\d+)*\s*\.?\s*', cleaned_text, flags=re.IGNORECASE)
                if len(after_number) > 1:
                    title = after_number[1].strip()
            return {
                'type': 'article',
                'number': number,
                'title': title,
                'full_text': cleaned_text,
                'original_html': original_html
            }

        sup_roman = r'[IVXLCDM\u00B9\u00B2\u00B3\u2070-\u2079]+'

        section_match = re.match(r'^Раздел\s+(' + sup_roman + r'(?:\.\d+)?|\d+(?:\.\d+)*(?:<sup>[^>]+</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)\s*(.*)$', cleaned_text, re.IGNORECASE)
        if section_match:
            number_raw = section_match.group(1)
            number = self._normalize_number_string(number_raw)
            title = section_match.group(2).strip()
            return {
                'type': 'section',
                'number': number,
                'number_normalized': number,
                'title': title,
                'full_text': cleaned_text,
                'original_html': original_html
            }

        chapter_match = re.match(r'^Глава\s+(' + sup_roman + r'(?:\.\d+)?|\d+(?:\.\d+)*(?:<sup>[^>]+</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?)\s*(.*)$', cleaned_text, re.IGNORECASE)
        if chapter_match:
            number_raw = chapter_match.group(1)
            number = self._normalize_number_string(number_raw)
            title = chapter_match.group(2).strip()
            return {
                'type': 'chapter',
                'number': number,
                'number_normalized': number,
                'title': title,
                'full_text': cleaned_text,
                'original_html': original_html
            }

        roman_section_match = re.match(r'^\s*([IVXLCDM\u00B9\u00B2\u00B3\u2070-\u2079]+)\s*\.\s*(.+)$', cleaned_text, re.IGNORECASE)
        if roman_section_match:
            number_raw = roman_section_match.group(1)
            number = self._normalize_number_string(number_raw)
            title = roman_section_match.group(2).strip()
            return {
                'type': 'section',
                'number': number,
                'number_normalized': number,
                'title': title,
                'full_text': cleaned_text,
                'original_html': original_html,
                'without_word': True
            }

        if cleaned_text.lower().startswith('приложение'):
            app_match = re.search(r'Приложение\s+[№]?\s*([\d\.]+|[IVXLCDM\u00B9\u00B2\u00B3\u2070-\u2079]+)', cleaned_text, re.IGNORECASE)
            number = app_match.group(1) if app_match else ""
            if re.match(r'^[IVXLCDM\u00B9\u00B2\u00B3\u2070-\u2079]+$', number.upper()):
                number = str(self.roman_to_int(number))
            return {
                'type': 'appendix',
                'number': number,
                'title': '',
                'full_text': cleaned_text,
                'is_main_appendix': False,
                'is_nested_appendix': False,
                'original_html': original_html,
                'prefix': original_text
            }

        match_paren = re.match(r'^\s*(\d+(?:\.\d+)*)\s*\)', cleaned_text)
        if match_paren:
            number = match_paren.group(1)
            dot_count = number.count('.')
            return {
                'type': 'numbered_paren',
                'number': number,
                'suffix': ')',
                'full_text': cleaned_text,
                'marker_style': 'paren',
                'dot_count': dot_count,
                'original_html': original_html
            }

        match_dot = re.match(r'^\s*(\d+(?:\.\d+)*)\s*\.(?:\s+)?(.*)$', cleaned_text)
        if match_dot:
            number = match_dot.group(1)
            return {
                'type': 'numbered_dot',
                'number': number,
                'suffix': '.',
                'full_text': cleaned_text,
                'marker_style': 'dot',
                'dot_count': number.count('.'),
                'original_html': original_html
            }

        letter_paren_match = re.match(r'^\s*([а-яё])\s*\)\s*', cleaned_text, re.IGNORECASE)
        if letter_paren_match:
            number = letter_paren_match.group(1).lower()
            return {
                'type': 'numbered_paren',
                'number': number,
                'suffix': ')',
                'full_text': cleaned_text,
                'marker_style': 'paren',
                'dot_count': 0,
                'original_html': original_html
            }

        letter_dot_match = re.match(r'^\s*([а-яё])\s*\.\s*', cleaned_text, re.IGNORECASE)
        if letter_dot_match:
            number = letter_dot_match.group(1).lower()
            return {
                'type': 'numbered_dot',
                'number': number,
                'suffix': '.',
                'full_text': cleaned_text,
                'marker_style': 'dot',
                'dot_count': 0,
                'original_html': original_html
            }

        return None

    def _process_structural_candidate_with_enumeration(self, candidate):
        if self.fragment_mode:
            self.logger.info(f"ФРАГМЕНТ: обработка структурного кандидата {candidate['type']} {candidate.get('number','')}")
            self._log_stack_state("до обработки")
        if self.stack and self.stack[-1].get('collected_content'):
            parent = self.stack[-1]
            collected_html = ''.join(parent.get('collected_content', []))
            if collected_html:
                soup = BeautifulSoup(collected_html, 'html.parser')
                full_text = self.extract_text(soup)
                parent['full_text'] = full_text
        text = candidate.get('full_text', '')
        opens, closes, net, starts_with_open, legal_close = self._para_quote_state(text)
        if self.quote_level > 0 or starts_with_open:
            if self.stack:
                self.stack[-1].setdefault('collected_content', []).append(candidate.get('original_html', ''))
            self.quote_level = max(0, self.quote_level + net)
            if legal_close and self.quote_level <= 0 and not starts_with_open:
                self.quote_level = 0
                self._pending_enum_parent = None
                self.pending_parent_for_next_content = None
            return
        self._close_enumeration_if_needed()
        if self.pending_parent_for_next_content:
            self.pending_parent_for_next_content = None
        prev_ends_with_colon = False
        if self.stack and self.stack[-1].get('full_text', '').rstrip().endswith(':'):
            prev_ends_with_colon = True
        number = candidate.get('number', '')
        is_start = self._is_starting_number(number)
        if prev_ends_with_colon and is_start:
            if text.lstrip().startswith('«'):
                if self.stack:
                    self.stack[-1].setdefault('collected_content', []).append(candidate.get('original_html', ''))
                self.quote_level = max(1, net if net != 0 else 1)
                self._pending_enum_parent = None
                self.pending_parent_for_next_content = None
                return
            parent_item = self.stack[-1]
            self._open_enumeration(parent_item, candidate)
            self.resolve_hierarchy_new(candidate)
            self._close_enumeration_if_needed()
            return
        self._log_stack_state(f"перед обработкой кандидата {candidate.get('type')} {candidate.get('number', '')}")
        self.resolve_hierarchy_new(candidate)
        new_item = self.stack[-1] if self.stack else None
        if new_item and self.log_queue:
            msg = f"Кандидат {candidate.get('type')} {candidate.get('number', '')} получил уровень {new_item['level']}, тип {new_item['type']}"
            self.log_queue.put(('log', msg, 'INFO'))
        self._log_stack_state(f"после добавления {candidate.get('type')} {candidate.get('number', '')}")
        self._close_enumeration_if_needed()
        if new_item and new_item.get('full_text', '').rstrip().endswith(':') and not new_item.get('full_text', '').lstrip().startswith('«'):
            self._pending_enum_parent = new_item

    def _process_nonstructural_tag_with_enumeration(self, tag, text, force_nonstructural=False):
        if not text and tag.find('img') is None:
            return

        if tag.find('img') is not None:
            if self.stack:
                self.stack[-1].setdefault('collected_content', []).append(str(tag))
            return

        opens, closes, net, starts_with_open, legal_close = self._para_quote_state(text)
        if force_nonstructural or self.quote_level > 0 or starts_with_open:
            if self.stack:
                self.stack[-1].setdefault('collected_content', []).append(str(tag))
            self.quote_level = max(0, self.quote_level + net)
            if starts_with_open and self.stack and self.stack[-1].get('full_text', '').rstrip().endswith(':'):
                self._pending_enum_parent = None
                self.pending_parent_for_next_content = None
            if legal_close and self.quote_level <= 0:
                self.quote_level = 0
                self._pending_enum_parent = None
                self.pending_parent_for_next_content = None
            return
        if self.pending_parent_for_next_content:
            self.pending_parent_for_next_content.setdefault('post_children_content', []).append(str(tag))
            return
        if self.enum_stack:
            if self.stack:
                self.stack[-1].setdefault('collected_content', []).append(str(tag))
            return
        if self.stack:
            self.stack[-1].setdefault('collected_content', []).append(str(tag))
        if text.rstrip().endswith(':') and not text.lstrip().startswith('«'):
            self._pending_enum_parent = self.stack[-1]
        else:
            self._pending_enum_parent = None

    def resolve_hierarchy_new(self, candidate):
        if self.fragment_mode:
            self.logger.info(f"ФРАГМЕНТ: разрешение иерархии для {candidate['type']} номер={candidate.get('number','')}")
            self._log_stack_state("resolve_hierarchy_new вход")
        c_type = candidate['type']
        if c_type in ('chapter', 'section', 'article', 'appendix', 'nested_appendix'):
            self.enum_stack = []
            self.pending_parent_for_next_content = None
            self._pending_enum_parent = None
        if c_type == 'appendix':
            is_main_appendix = candidate.get('is_main_appendix', False)
            if is_main_appendix:
                self.has_chapters_flag = False
                self.has_articles_flag = False
                self.in_appendix = True
                self.current_level = 1
                self.stack = []
                elem_type = 'appendix'
                level = 1
            else:
                if self.stack:
                    parent_level = 1
                    for item in reversed(self.stack):
                        if item['type'] in ['appendix', 'nested_appendix']:
                            parent_level = item['level']
                            break
                    level = parent_level + 1
                else:
                    level = 2
                elem_type = 'nested_appendix'
                self.in_appendix = True
            while self.stack and self.stack[-1].get('level', 0) >= level:
                if self.stack[-1].get('is_fragment_target', False):
                    break
                self.stack.pop()
            self._sync_enum_stack()
            self.add_to_stack_with_level(candidate, level, elem_type)
            return
        elif c_type in ('chapter', 'section'):
            self.has_chapters_flag = True
            if self.in_appendix:
                level = 2
            else:
                level = 1
            while self.stack and self.stack[-1].get('level', 0) >= level:
                if self.stack[-1].get('is_fragment_target', False):
                    break
                self.stack.pop()
            self._sync_enum_stack()
            self.add_to_stack_with_level(candidate, level, c_type)
            if c_type == 'section' and candidate.get('without_word'):
                parent_id = self._get_no_name_parent_id()
                if parent_id:
                    self.no_name_parents.add(parent_id)
            return
        elif c_type == 'article':
            self.has_articles_flag = True
            if self.in_appendix:
                base_level = 2
            else:
                base_level = 1
            if self.has_chapters_flag:
                level = base_level + 1
            else:
                level = base_level
            while self.stack and self.stack[-1].get('level', 0) >= level:
                if self.stack[-1].get('is_fragment_target', False):
                    break
                self.stack.pop()
            self._sync_enum_stack()
            self.add_to_stack_with_level(candidate, level, 'article')
            return
        elif c_type in ['numbered_dot', 'numbered_paren', 'subpoint']:
            self._process_numbered_element_new(candidate)
            return
        else:
            self.resolve_hierarchy_old(candidate)
            return

    def _process_numbered_element_new(self, candidate):
        if not self.stack:
            self.add_to_stack_with_level(candidate, 1, 'point')
            return
        adjacent = self.stack[-1]
        numbering_type = self.determine_numbering_type(candidate)

        if numbering_type == 'type1' and candidate.get('dot_count', 0) == 0:
            for i in range(len(self.stack)-1, -1, -1):
                if self.stack[i].get('type') == 'article':
                    level = self.stack[i]['level'] + 1
                    self.add_to_stack_with_level(candidate, level, 'part')
                    return

        if adjacent['type'] == 'article' and numbering_type == 'type1':
            level = adjacent['level'] + 1
            self.add_to_stack_with_level(candidate, level, 'part')
            return
        if adjacent['type'] in ('chapter', 'section', 'article'):
            level = adjacent['level'] + 1
            self.add_to_stack_with_level(candidate, level, 'point')
            return
        if adjacent['type'] in ('part', 'point', 'subpoint'):
            self.handle_numbered_with_numbered_parent(candidate, adjacent)
            return
        level = adjacent.get('level', 1) + 1
        self.add_to_stack_with_level(candidate, level, 'point')

    def handle_numbered_with_numbered_parent(self, candidate, adjacent):
        cand_marker = candidate.get('marker_style')
        adj_marker = adjacent.get('marker_style')
        cand_num_raw = candidate.get('number', '')
        cand_num = str(cand_num_raw).strip()
        cand_num = re.sub(r'[.)]$', '', cand_num)
        cand_num_lower = cand_num.lower()
        cand_type = self.determine_numbering_type(candidate)
        if (cand_marker != adj_marker or (cand_type != self.determine_numbering_type(adjacent) and cand_num_lower == 'а')) and (cand_num_lower == '1' or cand_num_lower == 'а'):
            new_level = adjacent['level'] + 1
            if adjacent['type'] == 'part':
                new_type = 'point'
            else:
                new_type = 'subpoint'
            self.add_to_stack_with_level(candidate, new_level, new_type)
            return
        target = None
        for item in reversed(self.stack):
            if item['type'] not in ('part', 'point', 'subpoint'):
                continue
            if item.get('marker_style') != cand_marker:
                continue
            if item.get('dot_count') != candidate.get('dot_count', 0):
                continue
            raw_number = re.sub(r'[.)]$', '', str(item.get('number', '')))
            temp_candidate = {'number': raw_number, 'marker_style': cand_marker}
            item_type = self.determine_numbering_type(temp_candidate)
            if item_type == cand_type:
                target = item
                break
            if item_type is not None and cand_type is not None:
                if cand_type.startswith('type2') and item_type.startswith('type4'):
                    continue
                if cand_type.startswith('type4') and item_type.startswith('type2'):
                    continue
                target = item
                break
        if target:
            while self.stack and self.stack[-1].get('level', 0) >= target['level']:
                if self.stack[-1].get('is_fragment_target', False):
                    break
                self.stack.pop()
            self._sync_enum_stack()
            self.add_to_stack_with_level(candidate, target['level'], target['type'], same_level_choice=True)
            return

        pattern_hash = self.create_pattern_hash(candidate, adjacent['type'])
        context_id = self.current_appendix_id if self.in_appendix else "main"

        if context_id in self.resolved_patterns and pattern_hash in self.resolved_patterns[context_id]:
            resolution = self.resolved_patterns[context_id][pattern_hash]
            level = resolution['level']
            elem_type = resolution['type']
            same_level_choice = resolution.get('same_level_choice', False)
            self.add_to_stack_with_level(candidate, level, elem_type, same_level_choice=same_level_choice)
            return

        try:
            relation, level, elem_type = self._ask_user_ambiguity(candidate, adjacent)
        except Exception as e:
            self.logger.error(f"User dialog failed: {e}, treating as sibling")
            relation, level, elem_type = 'sibling', adjacent['level'], adjacent['type']

        if relation == 'skip':
            return

        same_level_choice = (relation == 'sibling')
        if context_id not in self.resolved_patterns:
            self.resolved_patterns[context_id] = {}
        self.resolved_patterns[context_id][pattern_hash] = {
            'level': level,
            'type': elem_type,
            'same_level_choice': same_level_choice,
            'parent_type': adjacent['type'],
            'dot_count': candidate.get('dot_count', 0)
        }

        self.add_to_stack_with_level(candidate, level, elem_type, same_level_choice=same_level_choice)

    def handle_extension_case(self, candidate, adjacent, numbering_type):
        pattern_hash = self.create_pattern_hash(candidate, adjacent['type'] if adjacent else None)
        context_id = self.current_appendix_id if self.in_appendix else "main"
        saved_pattern = self.check_saved_pattern_with_level(adjacent['type'] if adjacent else None, candidate.get('dot_count', 0), pattern_hash, context_id)
        if saved_pattern:
            saved_type = saved_pattern['type']
            saved_level = saved_pattern.get('level', adjacent.get('level', 1) + 1 if adjacent else 1)
            same_level_choice = saved_pattern.get('same_level_choice', False)
            candidate['_from_saved_pattern'] = True
            self.add_to_stack_with_level(candidate, saved_level, saved_type, same_level_choice=same_level_choice)
            return
        for elem_info in self.ambiguous_elements:
            if elem_info['pattern_hash'] == pattern_hash and elem_info['context_id'] == context_id:
                return
        element_info = self.create_ambiguous_element_info(candidate, adjacent, pattern_hash, context_id)
        self.ambiguous_elements.append(element_info)
        candidate['is_ambiguous'] = True
        candidate['pattern_hash'] = pattern_hash
        candidate['context_id'] = context_id

    def handle_level_up_case(self, candidate, adjacent, numbering_type):
        candidate_dot_count = candidate.get('dot_count', 0)
        target_element = None
        target_index = -1
        for i in range(len(self.stack) - 1, -1, -1):
            item = self.stack[i]
            if item['type'] in ['part', 'point', 'subpoint', 'subpoint_lower']:
                item_numbering_type = self.determine_numbering_type(item)
                item_dot_count = item.get('dot_count', 0)
                if (item_numbering_type == numbering_type and item_dot_count == candidate_dot_count):
                    target_element = item
                    target_index = i
                    break
        if target_element:
            while len(self.stack) > target_index:
                if self.stack[-1].get('is_fragment_target', False):
                    break
                self.stack.pop()
            self._sync_enum_stack()
            level = target_element.get('level', 1)
            elem_type = target_element['type']
            self.add_to_stack_with_level(candidate, level, elem_type, same_level_choice=True)
        else:
            level = 1
            for i in range(len(self.stack) - 1, -1, -1):
                item = self.stack[i]
                if item['type'] in ['chapter', 'section', 'article', 'appendix', 'nested_appendix', 'preamble']:
                    level = item.get('level', 1) + 1
                    break
            if numbering_type == 'type1' and self.doc_type == 'law':
                elem_type = 'part'
            elif numbering_type == 'type1' and self.doc_type == 'regulation':
                elem_type = 'point'
            elif numbering_type == 'type2':
                elem_type = 'point'
            elif numbering_type == 'type3':
                elem_type = 'subpoint'
            elif numbering_type == 'type4':
                elem_type = 'subpoint'
            else:
                elem_type = 'point'
            while self.stack and self.stack[-1].get('level', 0) >= level:
                if self.stack[-1].get('is_fragment_target', False):
                    break
                self.stack.pop()
            self._sync_enum_stack()
            self.add_to_stack_with_level(candidate, level, elem_type)

    def handle_type_change_case(self, candidate, adjacent, numbering_type):
        candidate_numbering_type = numbering_type
        candidate_dot_count = candidate.get('dot_count', 0)
        candidate_number = str(candidate.get('number', ''))
        parent_in_stack = None
        for item in reversed(self.stack):
            item_number = str(item.get('number', ''))
            if item_number and candidate_number.startswith(item_number + '.'):
                parent_in_stack = item
                break
        if parent_in_stack:
            pattern_hash = self.create_pattern_hash(candidate, parent_in_stack['type'])
            context_id = self.current_appendix_id if self.in_appendix else "main"
            saved_pattern = self.check_saved_pattern_with_level(parent_in_stack['type'], candidate_dot_count, pattern_hash, context_id)
            if saved_pattern:
                saved_level = saved_pattern.get('level', 1)
                saved_type = saved_pattern['type']
                same_level_choice = saved_pattern.get('same_level_choice', False)
                parent_level = parent_in_stack.get('level', 1)
                if saved_level == parent_level + 1:
                    self.add_to_stack_with_level(candidate, saved_level, saved_type, same_level_choice=same_level_choice)
                    return
                elif saved_level > parent_level + 1:
                    pass
                elif saved_level < parent_level:
                    found_in_stack = False
                    for item in reversed(self.stack):
                        item_type = item.get('type')
                        item_level = item.get('level', 1)
                        if item_type == saved_type and item_level == saved_level:
                            while self.stack and self.stack[-1].get('level', 0) >= saved_level:
                                if self.stack[-1].get('is_fragment_target', False):
                                    break
                                self.stack.pop()
                            self._sync_enum_stack()
                            self.add_to_stack_with_level(candidate, saved_level, saved_type, same_level_choice=same_level_choice)
                            found_in_stack = True
                            break
                    if found_in_stack:
                        return
                    else:
                        parent_type_found = False
                        while self.stack and not parent_type_found:
                            last_item = self.stack[-1]
                            last_item_type = last_item.get('type', '')
                            if last_item_type not in ['part', 'point', 'subpoint']:
                                parent_type_found = True
                                parent_level = last_item.get('level', 1)
                                self.add_to_stack_with_level(candidate, parent_level + 1, saved_type, same_level_choice=same_level_choice)
                                return
                            self._safe_pop()
                        if not parent_type_found:
                            self.add_to_stack_with_level(candidate, 1, saved_type, same_level_choice=same_level_choice)
                            return
            self.handle_extension_case(candidate, parent_in_stack, numbering_type)
            return
        is_extended = self.is_extended_element(candidate)
        if is_extended:
            self.handle_extension_case(candidate, adjacent, numbering_type)
            return
        expected_type = None
        if numbering_type == 'type1':
            if self.stack and self.stack[-1].get('type') == 'article':
                expected_type = 'part'
            else:
                expected_type = 'point'
        elif numbering_type == 'type2':
            expected_type = 'point'
        elif numbering_type == 'type3':
            expected_type = 'subpoint'
        elif numbering_type == 'type4':
            expected_type = 'subpoint'
        else:
            expected_type = 'point'
        same_type_candidates = []
        for i in range(len(self.stack) - 1, -1, -1):
            item = self.stack[i]
            if item['type'] not in ['part', 'point', 'subpoint']:
                break
            if item['type'] == expected_type:
                if self.is_extension_of(item, candidate) or self.is_extension_of(candidate, item):
                    continue
                same_type_candidates.append(item)
        if same_type_candidates:
            best = min(same_type_candidates, key=lambda x: x['level'])
            level = best['level']
            elem_type = best['type']
            while self.stack and self.stack[-1].get('level', 0) >= level:
                if self.stack[-1].get('is_fragment_target', False):
                    break
                self.stack.pop()
            self._sync_enum_stack()
            self.add_to_stack_with_level(candidate, level, elem_type, same_level_choice=True)
            return
        found_same_element = None
        found_element_index = -1
        candidate_base_type = candidate_numbering_type.replace('_extended', '')
        for i in range(len(self.stack) - 1, -1, -1):
            item = self.stack[i]
            if item['type'] not in ['part', 'point', 'subpoint']:
                break
            item_numbering_type = self.determine_numbering_type(item)
            item_base_type = item_numbering_type.replace('_extended', '') if item_numbering_type else None
            if item_base_type == candidate_base_type:
                if candidate_base_type == 'type2':
                    found_same_element = item
                    break
                if candidate_dot_count == item.get('dot_count', 0):
                    found_same_element = item
                    break
        if found_same_element:
            level = found_same_element.get('level', 1)
            elem_type = found_same_element['type']
            while self.stack and self.stack[-1].get('level', 0) >= level:
                if self.stack[-1].get('is_fragment_target', False):
                    break
                self.stack.pop()
            self._sync_enum_stack()
            self.add_to_stack_with_level(candidate, level, elem_type, same_level_choice=True)
            return
        adjacent_level = adjacent.get('level', 1)
        level = adjacent_level + 1
        if adjacent['type'] == 'part':
            elem_type = 'point'
        elif adjacent['type'] == 'point':
            elem_type = 'subpoint'
        elif adjacent['type'] == 'subpoint':
            elem_type = 'subpoint'
        else:
            if numbering_type == 'type1':
                if self.stack and self.stack[-1].get('type') == 'article':
                    elem_type = 'part'
                else:
                    elem_type = 'point'
            elif numbering_type == 'type2':
                elem_type = 'point'
            elif numbering_type == 'type3':
                elem_type = 'subpoint'
            elif numbering_type == 'type4':
                elem_type = 'subpoint'
            else:
                elem_type = 'point'
        while self.stack and self.stack[-1].get('level', 0) >= level:
            if self.stack[-1].get('is_fragment_target', False):
                break
            self.stack.pop()
        self._sync_enum_stack()
        self.add_to_stack_with_level(candidate, level, elem_type)

    def create_ambiguous_element_info(self, candidate, adjacent, pattern_hash, context_id):
        return {
            'candidate': candidate,
            'adjacent': adjacent,
            'pattern_hash': pattern_hash,
            'context_id': context_id
        }

    def add_to_stack_with_level(self, candidate, level, element_type, same_level_choice=False):
        if self.fragment_mode:
            self.logger.info(f"ФРАГМЕНТ: добавление в стек {element_type} номер={candidate.get('number','')} уровень={level}")
            self._log_stack_state("перед добавлением")
        self.current_level = level
        candidate['type'] = element_type
        marker_style = candidate.get('marker_style', '')
        candidate_number = str(candidate.get('number', ''))
        if element_type in ['part', 'point', 'subpoint']:
            suffix = candidate.get('suffix', '')
            if suffix == '.':
                suffix = ''
            item_number = candidate_number + suffix
        else:
            item_number = candidate_number
        actual_level = level
        if '.' in candidate_number:
            base_number = candidate_number.split('.')[0]
            for idx, item in enumerate(self.stack):
                if str(item.get('number', '')) == base_number and item['type'] == element_type:
                    actual_level = item.get('level', 1)
                    while len(self.stack) > idx + 1:
                        if self.stack[-1].get('is_fragment_target', False):
                            break
                        self.stack.pop()
                    break
        while self.stack and self.stack[-1].get('level', 0) >= actual_level:
            if self.stack[-1].get('is_fragment_target', False):
                break
            self.stack.pop()
        self._sync_enum_stack()
        parent_id = self.stack[-1]['id'] if self.stack else None
        anchor = self._get_unique_item_id(element_type, item_number, parent_id)
        display_text = self.get_display_text(element_type, item_number, candidate, candidate.get('title', ''))
        original_html = candidate.get('original_html', '')
        head_revisions = []
        title = candidate.get('title', '')
        if title and element_type in ('chapter', 'section', 'article', 'appendix', 'nested_appendix'):
            head_revisions = [{'head_text': title}]
        item_prefix_revisions = []
        if element_type in ('appendix', 'nested_appendix') and candidate.get('prefix'):
            item_prefix_revisions.append({'prefix_text': candidate['prefix']})
        item = {
            'id': anchor,
            'type': element_type,
            'number': item_number,
            'display_text': display_text,
            'full_text': candidate.get('full_text', ''),
            'title': title,
            'level': actual_level,
            'children': [],
            'parent_id': parent_id,
            'dot_count': candidate.get('dot_count', 0),
            'marker_style': marker_style,
            'is_main_appendix': candidate.get('is_main_appendix', False),
            'is_nested_appendix': candidate.get('is_nested_appendix', False),
            'skip_internals': candidate.get('skip_internals', False),
            'same_level_choice': same_level_choice,
            'original_html': original_html,
            'collected_content': [],
            'head_revisions': head_revisions,
            'item_prefix_revisions': item_prefix_revisions,
        }
        if original_html and element_type in ('point', 'part', 'subpoint'):
            item['collected_content'].append(original_html)
        self.stack.append(item)
        if parent_id:
            for toc_item in self.toc_items:
                if self._add_child_to_parent(toc_item, parent_id, item):
                    break
        elif actual_level == 1:
            self.toc_items.append(item)
        if self.fragment_mode:
            self.logger.info(f"ФРАГМЕНТ: добавлен элемент {item['id']}, стек теперь {len(self.stack)} элементов")

    def _add_child_to_parent(self, parent_item, parent_id, child_item):
        if parent_item is None:
            return False
        if parent_item['id'] == parent_id:
            children = parent_item.get('children', [])
            if not any(child['id'] == child_item['id'] for child in children):
                children.append(child_item)
            return True
        for child in parent_item.get('children', []):
            if self._add_child_to_parent(child, parent_id, child_item):
                return True
        return False

    def resolve_hierarchy_old(self, candidate):
        c_type = candidate['type']
        if c_type == 'appendix':
            self.in_appendix = True
            if self.stack:
                for i, item in enumerate(self.stack):
                    if item['type'] == 'appendix':
                        self.stack = self.stack[:i+1]
                        break
            self.add_to_stack_with_level(candidate, 1, 'appendix')
        elif c_type in ('chapter', 'section'):
            level = 2 if self.in_appendix else 1
            while self.stack and self.stack[-1].get('level', 0) >= level:
                self.stack.pop()
            self.add_to_stack_with_level(candidate, level, c_type)
        elif c_type == 'article':
            level = 3 if self.has_chapters_flag else 2
            if self.in_appendix:
                level = 3
            while self.stack and self.stack[-1].get('level', 0) >= level:
                self.stack.pop()
            self.add_to_stack_with_level(candidate, level, 'article')
        elif c_type in ('point', 'subpoint'):
            self._process_numbered_element_new(candidate)

    def _strip_number_marker_from_first_body_paragraph(self, html_text, item_number, item_type):
        if not item_number or item_type not in ['part', 'point', 'subpoint']:
            return html_text
        number_clean = str(item_number).strip().rstrip('.)')
        escaped = re.escape(number_clean)
        pattern = re.compile(r'^' + escaped + r'(?:\.|\)|\)\s+|\s+\.|\s+\)|\s+\.\s+|\s+\)\s+|\s+)(?:\s|&nbsp;|\u00A0|\t|\n)*', re.IGNORECASE | re.UNICODE)
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_text, 'html.parser')
            first_text = None
            for node in soup.find_all(string=True, recursive=True):
                if node.parent.name not in ['img', 'script', 'style']:
                    first_text = node
                    break
            if first_text:
                stripped_text = first_text.lstrip(' \t\n\r\x0b\x0c\u00A0')
                if pattern.match(stripped_text):
                    new_text = pattern.sub('', stripped_text, count=1)
                    new_text = new_text.lstrip(' \t\n\r\x0b\x0c\u00A0')
                    first_text.replace_with(new_text)
                    return str(soup)
        except Exception:
            pass
        return html_text

    def convert_to_new_format(self, items, start_counter=1):
        if items is None:
            return [], start_counter
        new_items = []
        counter = start_counter
        types_without_marker = ['part', 'point', 'subpoint']
        for old_item in items:
            if old_item is None:
                continue
            if old_item.get('_is_table_child', False):
                full_html = ''.join(old_item.get('collected_content', []))
                if not full_html and old_item.get('original_html'):
                    full_html = old_item['original_html']
                if not full_html and old_item.get('revisions'):
                    for rev in old_item['revisions']:
                        for block in rev.get('body', []):
                            if block.get('type') == 'table_fragment':
                                full_html = block.get('html_text', '')
                                break
                body = [{'type': 'table_fragment', 'html_text': full_html, 'order': 1}]
                revision = {'body': body}
                new_item = {
                    'item_id': old_item['id'],
                    'item_type': old_item['type'],
                    'item_number': old_item.get('number', ''),
                    'item_level': old_item['level'],
                    'revisions': [revision],
                }
                if old_item.get('head_revisions'):
                    new_item['head_revisions'] = old_item['head_revisions']
                if old_item.get('item_note'):
                    new_item['item_note'] = old_item['item_note']
                if 'item_prefix_revisions' in old_item and old_item['item_prefix_revisions']:
                    new_item['item_prefix_revisions'] = old_item['item_prefix_revisions']
                children_result, counter = self.convert_to_new_format(old_item.get('children', []), counter)
                if children_result:
                    new_item['item_children'] = children_result
                new_items.append(new_item)
                continue
            if old_item['type'] == 'structured_table':
                if 'revisions' in old_item and old_item['revisions']:
                    revision = old_item['revisions'][0]
                    body = revision.get('body', [])
                    for block in body:
                        if block.get('type') in ('paragraph', 'table_header', 'table_fragment'):
                            block['html_text'] = self._wrap_table_html(block['html_text'])
                else:
                    body = []
                    order = 1
                    if old_item.get('thead_html'):
                        body.append({'type': 'table_header', 'html_text': self._wrap_table_html(old_item['thead_html']), 'order': order})
                        order += 1
                    if old_item.get('_nonstructural_prefix'):
                        for part_html in old_item['_nonstructural_prefix']:
                            body.append({'type': 'paragraph', 'html_text': self._wrap_table_html(part_html), 'order': order})
                            order += 1
                    for child in old_item.get('children', []):
                        body.append({'type': 'child_ref', 'item_id': child['id'], 'order': order})
                        order += 1
                    revision = {'body': body}
            else:
                if old_item['type'] in ['article', 'chapter', 'section', 'appendix', 'nested_appendix']:
                    collected = old_item.get('collected_content', [])
                    full_html = ''.join(collected) if collected else ''
                else:
                    collected = old_item.get('collected_content', [])
                    full_html = ''.join(collected) if collected else old_item.get('original_html', '')
                body = []
                order = 1
                if full_html.strip():
                    soup = BeautifulSoup(full_html, 'html.parser')
                    children_tags = [child for child in soup.children if hasattr(child, 'name')]
                    if children_tags:
                        for idx, child in enumerate(children_tags):
                            child_html = str(child)
                            child_html = self.remove_exactly_one_leading_whitespace(child_html)
                            has_img = '<img' in child_html.lower()
                            if idx == 0 and old_item['type'] in types_without_marker and not has_img:
                                child_html = self._strip_number_marker_from_first_body_paragraph(
                                    html_text=child_html,
                                    item_number=old_item.get('number', ''),
                                    item_type=old_item['type']
                                )
                            child_html = self._wrap_table_html(child_html)
                            body.append({'type': 'paragraph', 'html_text': child_html, 'order': order})
                            order += 1
                    else:
                        full_html_clean = re.sub(r'^(\s|&nbsp;|&#160;)+', '', full_html)
                        has_img = '<img' in full_html_clean.lower()
                        if old_item['type'] in types_without_marker and not has_img:
                            full_html_clean = self._strip_number_marker_from_first_body_paragraph(
                                html_text=full_html_clean,
                                item_number=old_item.get('number', ''),
                                item_type=old_item['type']
                            )
                        full_html_clean = self._wrap_table_html(full_html_clean)
                        body.append({'type': 'paragraph', 'html_text': full_html_clean, 'order': order})
                        order += 1
                for child in old_item.get('children', []):
                    body.append({'type': 'child_ref', 'item_id': child['id'], 'order': order})
                    order += 1
                if old_item.get('post_children_content'):
                    for content in old_item['post_children_content']:
                        if content and content.strip():
                            content = self._wrap_table_html(content)
                            body.append({'type': 'paragraph', 'html_text': content, 'order': order})
                            order += 1
                revision = {'body': body}
                if old_item.get('title') and old_item['type'] not in types_without_marker:
                    if old_item['type'] in ('article', 'chapter', 'section', 'appendix', 'nested_appendix'):
                        if 'head_revisions' not in old_item:
                            old_item['head_revisions'] = []
                        if not any(r.get('head_text') == old_item['title'] for r in old_item['head_revisions']):
                            old_item['head_revisions'].append({'head_text': old_item['title']})
                    else:
                        revision['item_head'] = old_item['title']
            new_item = {
                'item_id': old_item['id'],
                'item_type': old_item['type'],
                'item_number': old_item.get('number', ''),
                'item_level': old_item['level'],
                'revisions': [revision],
            }
            if old_item.get('head_revisions'):
                new_item['head_revisions'] = old_item['head_revisions']
            if old_item.get('item_note'):
                new_item['item_note'] = old_item['item_note']
            if 'item_prefix_revisions' in old_item and old_item['item_prefix_revisions']:
                new_item['item_prefix_revisions'] = old_item['item_prefix_revisions']
            if not old_item.get('_is_table_child', False) and old_item['type'] != 'structured_table':
                children_result, counter = self.convert_to_new_format(old_item.get('children', []), counter)
                if children_result:
                    new_item['item_children'] = children_result
            elif old_item['type'] == 'structured_table':
                children_result, counter = self.convert_to_new_format(old_item.get('children', []), counter)
                if children_result:
                    new_item['item_children'] = children_result
            new_items.append(new_item)
        return new_items, counter

    def remove_exactly_one_leading_whitespace(self, html_str):
        if not html_str:
            return html_str
        soup = BeautifulSoup(html_str, 'html.parser')
        tag = soup.find()
        if not tag:
            return html_str
        first_text_node = tag.find(string=True, recursive=False)
        if first_text_node:
            content = str(first_text_node)
            pattern = r'^([ \u00A0])(?![ \u00A0])'
            if re.match(pattern, content):
                new_content = re.sub(pattern, '', content, count=1)
                first_text_node.replace_with(new_content)
                return str(tag)
        return html_str

    def generate_toc(self):
        try:
            self.used_ids.clear()
            if self.fragment_mode and self.fragment_element_id:
                single_item = self.process_fragment(self.original_html, self.fragment_element_id)
                if single_item:
                    if self.root_number is not None and not single_item.get('item_number'):
                        single_item['item_number'] = self.root_number
                    if self.root_type is not None:
                        single_item['item_type'] = self.root_type
                    return [single_item], self.ambiguous_elements
                return [], []
            self.process_structured_elements_new()
            self._clean_appendix_signatures(self.toc_items)
            self.toc_items, _ = self.convert_to_new_format(self.toc_items, 1)
            if self.doc_type == 'regulation' and not self.fragment_mode:
                missing = []
                if not self.term_number:
                    missing.append("номер созыва (term_number)")
                if not self.session_number:
                    missing.append("номер сессии (session_number)")
                if not self.npa_number:
                    missing.append("номер НПА (npa_number)")
                if not self.date_passed:
                    missing.append("дата принятия (date_passed)")
                if not self.governor_post_html:
                    missing.append("должность председателя (governor_post_html)")
                if not self.governor_name:
                    missing.append("ФИО председателя (governor_name)")
                if missing:
                    error_msg = f"Отсутствуют обязательные параметры для постановления: {', '.join(missing)}"
                    self.errors.append(error_msg)
                    raise Exception(error_msg)
            elif self.doc_type == 'law' and not self.fragment_mode:
                missing = []
                if not self.npa_number:
                    missing.append("номер НПА (npa_number)")
                if not self.date_signed:
                    missing.append("дата подписания (date_signed)")
                if not self.governor_post_html:
                    missing.append("должность губернатора (governor_post_html)")
                if not self.governor_name:
                    missing.append("ФИО губернатора (governor_name)")
                if missing:
                    error_msg = f"Отсутствуют обязательные параметры для закона: {', '.join(missing)}"
                    self.errors.append(error_msg)
                    raise Exception(error_msg)
            if self.root_number is not None and self.toc_items:
                self.toc_items[0]['item_number'] = str(self.root_number).rstrip('.')
            if self.root_type is not None and self.toc_items:
                self.toc_items[0]['item_type'] = self.root_type
            return self.toc_items, self.ambiguous_elements
        except Exception as e:
            self.errors.append(f"Ошибка при генерации TOC: {str(e)}")
            raise