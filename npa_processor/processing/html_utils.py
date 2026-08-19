"""HTML-утилиты для извлечения и очистки HTML."""

import copy
import difflib
import json
import re

from bs4 import BeautifulSoup

from npa_processor.constants import TYPE_TO_RUSSIAN
from npa_processor.processing.text_utils import clean_number, safe_re_sub, strip_thinking_tags


def clean_and_unwrap_html(html_text, is_table_child=False):
    if not html_text:
        return ""
    html_text = safe_re_sub(r'^(?:\s*<p[^>]*>\s*(?:&nbsp;|\s|<br/>|<br>)*</p>\s*)+', '', html_text, flags=re.IGNORECASE)
    html_text = safe_re_sub(r'(?:\s*<p[^>]*>\s*(?:&nbsp;|\s|<br/>|<br>)*</p>\s*)+$', '', html_text, flags=re.IGNORECASE)
    if is_table_child:
        soup = BeautifulSoup(html_text, 'html.parser')
        table_tag = soup.find('table')
        if table_tag:
            rows = table_tag.find_all('tr')
            html_text = "\n".join(str(row) for row in rows) if rows else table_tag.decode_contents()
    return html_text.strip()


def extract_paragraphs_by_indices(html: str, range_str: str, log_callback=None) -> str:
    if not html:
        return ''
    range_str = range_str.strip().lower() if range_str else ''
    if range_str and ('<p' in range_str or '<div' in range_str or '<table' in range_str):
        if log_callback:
            log_callback("  WARNING: range_str выглядит как HTML, используем 'all'", 'warning')
        range_str = 'all'
    soup = BeautifulSoup(html, 'html.parser')
    all_blocks = [c for c in soup.children if hasattr(c, 'name') and c.name]
    if not all_blocks:
        all_blocks = soup.find_all(['p', 'div', 'table', 'tr'])
    if not all_blocks:
        return html.strip()
    selected_blocks = []
    if range_str == 'all' or not range_str:
        first_q = html.find('«')
        last_q = html.rfind('»')
        if first_q != -1 and last_q != -1 and last_q > first_q:
            start_idx = -1
            # Начало цитаты-блока — первый блок, который НАЧИНАЕТСЯ с «.
            # (не любой блок, содержащий «: в вводном абзаце «...изложить в
            #  следующей редакции» может встречаться вложенная цитата с названием
            #  закона «О предоставлении...», которая НЕ является началом блока)
            for i, block in enumerate(all_blocks):
                if block.get_text(strip=True).lstrip().startswith('«'):
                    start_idx = i
                    break
            if start_idx == -1:
                # fallback: ни один блок не начинается с « — берём первый,
                # содержащий открывающую кавычку (возможно « внутри предложения)
                for i, block in enumerate(all_blocks):
                    if '«' in block.get_text():
                        start_idx = i
                        break
            end_idx = -1
            for i in range(len(all_blocks)-1, -1, -1):
                if '»' in all_blocks[i].get_text():
                    end_idx = i
                    break
            if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                selected_blocks = all_blocks[start_idx:end_idx+1]
            else:
                selected_blocks = all_blocks
        else:
            selected_blocks = all_blocks
    else:
        indices = set()
        parts = range_str.split(',')
        for part in parts:
            part = part.strip()
            if '-' in part:
                try:
                    s, e = map(int, part.split('-'))
                    for i in range(s, e + 1):
                        indices.add(i)
                except ValueError:
                    pass
            elif part.isdigit():
                indices.add(int(part))
        for idx in sorted(indices):
            if 1 <= idx <= len(all_blocks):
                selected_blocks.append(all_blocks[idx - 1])
            else:
                if log_callback:
                    log_callback(f"  Абзац {idx} выходит за пределы элемента (всего {len(all_blocks)})", 'warning')
        if not selected_blocks:
            if log_callback:
                log_callback(f"  Абсолютные индексы не найдены для '{range_str}'. Попытка извлечь N-ю цитату...", 'warning')
            quotes = []
            current_quote = []
            in_quote = False
            for block in all_blocks:
                text = block.get_text(strip=True)
                starts_with_quote = text.lstrip().startswith('«')
                ends_with_quote = '»' in text
                if starts_with_quote:
                    if in_quote and current_quote:
                        quotes.append(current_quote)
                    current_quote = [block]
                    in_quote = True
                    if ends_with_quote:
                        quotes.append(current_quote)
                        current_quote = []
                        in_quote = False
                elif in_quote:
                    current_quote.append(block)
                    if ends_with_quote:
                        quotes.append(current_quote)
                        current_quote = []
                        in_quote = False
            if in_quote and current_quote:
                quotes.append(current_quote)
            if quotes:
                if '-' in range_str:
                    try:
                        s, e = map(int, range_str.split('-'))
                        for i in range(s, e + 1):
                            if 1 <= i <= len(quotes):
                                selected_blocks.extend(quotes[i-1])
                    except (ValueError, IndexError):
                        pass
                elif range_str.isdigit():
                    idx = int(range_str)
                    if 1 <= idx <= len(quotes):
                        selected_blocks = quotes[idx-1]
                    else:
                        if len(quotes) == 1:
                            quote_html = '\n'.join(str(b) for b in quotes[0])
                            clean_quote = safe_re_sub(r'^\s*«', '', quote_html)
                            parts = split_html_by_leading_number(clean_quote, [str(idx) + ')', str(idx) + '.'])
                            for key, val in parts.items():
                                if key.rstrip('.)') == str(idx):
                                    selected_blocks = [BeautifulSoup(val, 'html.parser')]
                                    break
                        if not selected_blocks:
                            selected_blocks = [b for q in quotes for b in q]
                else:
                    if len(quotes) == 1:
                        quote_html = '\n'.join(str(b) for b in quotes[0])
                        clean_quote = safe_re_sub(r'^\s*«', '', quote_html)
                        markers = [range_str, range_str + ')', range_str + '.']
                        parts = split_html_by_leading_number(clean_quote, markers)
                        for key, val in parts.items():
                            if key.rstrip('.)') == range_str.rstrip('.)'):
                                selected_blocks = [BeautifulSoup(val, 'html.parser')]
                                break
                    if not selected_blocks:
                        selected_blocks = [b for q in quotes for b in q]
    if not selected_blocks:
        if log_callback:
            log_callback("  Не найдены блоки для извлечения. Возвращаем HTML как есть.", 'warning')
        return '\n'.join(str(b) for b in all_blocks if str(b).strip())

    # ========== ИСПРАВЛЕННЫЙ БЛОК УДАЛЕНИЯ ВНЕШНИХ КАВЫЧЕК ==========
    if selected_blocks:
        # Удаляем внешние кавычки ТОЛЬКО в пределах выбранных блоков
        # 1. Найти первый блок среди выбранных, который начинается с «
        first_open_idx = None
        for i, block in enumerate(selected_blocks):
            text = block.get_text(strip=True)
            if text.lstrip().startswith('«'):
                first_open_idx = i
                break
        if first_open_idx is not None:
            first_block = selected_blocks[first_open_idx]
            # Ищем первый текстовый узел с «
            first_node = first_block.find(string=True)
            if first_node and '«' in str(first_node):
                original = str(first_node)
                pos = original.find('«')
                if pos != -1:
                    # Удаляем только эту кавычку, остальное оставляем
                    first_node.replace_with(original[:pos] + original[pos+1:])

        # 2. Найти последний блок среди выбранных, который содержит » и заканчивается на неё
        last_close_idx = None
        for i in range(len(selected_blocks)-1, -1, -1):
            block = selected_blocks[i]
            text = block.get_text(strip=True)
            # Проверяем, заканчивается ли текст на » (после удаления завершающей пунктуации)
            tail = re.sub(r'[\s;,.!?…]+$', '', text.rstrip())
            if tail.endswith('»'):
                last_close_idx = i
                break
        if last_close_idx is not None:
            last_block = selected_blocks[last_close_idx]
            # Находим последний текстовый узел, содержащий »
            last_nodes = list(last_block.find_all(string=True))
            last_quote_node = None
            last_quote_pos = -1
            for node in reversed(last_nodes):
                text = str(node)
                pos = text.rfind('»')
                if pos != -1:
                    last_quote_node = node
                    last_quote_pos = pos
                    break
            if last_quote_node is not None:
                original = str(last_quote_node)
                before_quote = original[:last_quote_pos]
                after_quote = original[last_quote_pos+1:]
                # Удаляем пунктуацию сразу после кавычки (пробелы, ; , . ! ? …)
                after_quote = re.sub(r'^[\s;,.!?…]+', '', after_quote)
                new_text = before_quote + after_quote
                last_quote_node.replace_with(new_text)
                # Если блок после этого стал пустым, удаляем его
                if not last_block.get_text(strip=True):
                    last_block.decompose()
    # ========== КОНЕЦ ИСПРАВЛЕННОГО БЛОКА ==========

    result_html = '\n'.join(str(b) for b in selected_blocks if b and str(b).strip())
    result_html = safe_re_sub(r';{2,}', ';', result_html)
    if log_callback:
        log_callback(f"  Извлечён HTML по индексу '{range_str}' (длина {len(result_html)})", 'source')
    return result_html.strip()

def extract_leading_number(html):
    """Извлекает ведущий номер первого абзаца HTML-фрагмента.

    Возвращает строку с номером (без скобки/точки) или None,
    если первый абзац не начинается с маркера (цифра или буква + скобка/точка).
    """
    if not html:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    first_para = soup.find(['p', 'div'])
    if first_para is None:
        first_para = soup
    text = first_para.get_text(strip=True)
    text = safe_re_sub(r'^[«»"\'“”‘’\s]+', '', text)
    m = re.match(r'^(\d+(?:\.\d+)?|[а-яё])(?:[\.\)])\s*', text)
    if m:
        return m.group(1).rstrip('.)')
    return None


def extract_html_for_added_element(source_html, range_str, child_number, log_callback=None):
    """Извлекает HTML для добавляемого элемента с защитой от неверного description.

    Проблема: модель на этапе 3 может указать в description неверные абсолютные
    номера абзацев, из-за чего по индексам извлекается фрагмент, начинающийся
    НЕ с номера добавляемого элемента (например, для «пункт 7» попадает и «пункт 6»).
    Это приводит к ложному диалогу «неоднозначности» на этапе перестройки.

    Функция проверяет, что первый абзац извлечённого HTML начинается с номера
    добавляемого элемента (child_number), и если нет — ищет корректный фрагмент
    по ведущему маркеру в исходном HTML.
    """
    if not source_html:
        return ''
    extracted = extract_paragraphs_by_indices(source_html, range_str, log_callback)
    if not extracted:
        return ''
    expected_num = str(child_number).strip().rstrip('.)')
    if not expected_num:
        return extracted
    first_num = extract_leading_number(extracted)
    if first_num is not None and first_num == expected_num:
        return extracted
    # Ведущий маркер не совпадает с номером добавляемого элемента.
    # Пытаемся найти фрагмент, начинающийся с ожидаемого маркера.
    if log_callback:
        log_callback(
            f"  add: первый абзац извлечённого HTML начинается с '{first_num}', "
            f"ожидался '{expected_num}'. Ищем фрагмент по маркеру...", 'warning'
        )
    clean_source = safe_re_sub(r'[«»]', '', source_html)
    markers = [expected_num + ')', expected_num + '.', expected_num]
    parts = split_html_by_leading_number(clean_source, markers)
    found_fragment = None
    for key, val in parts.items():
        if key.rstrip('.)') == expected_num:
            found_fragment = val
            break
    if found_fragment:
        if log_callback:
            log_callback(f"  add: найден фрагмент по маркеру '{expected_num}' (длина {len(found_fragment)})", 'info')
        return clean_description_html(found_fragment)
    # Не удалось найти по маркеру — возвращаем извлечённое по description.
    if log_callback:
        log_callback(
            f"  add: не удалось найти фрагмент по маркеру '{expected_num}', "
            f"используем извлечённый по description", 'warning'
        )
    return extracted


def remove_leading_number_from_html(html, item_number):
    if not html or not item_number:
        return html
    item_number = str(item_number)
    base = re.escape(item_number.rstrip('.)'))
    pattern_tag = r'^\s*(<[^>]+>)\s*' + base + r'[\.\)]?\s*'
    result = safe_re_sub(pattern_tag, r'\1', html, count=1, flags=re.DOTALL)
    if result != html:
        return result
    pattern_plain = r'^\s*' + base + r'[\.\)]?\s*'
    return safe_re_sub(pattern_plain, '', html, count=1)

def clean_description_html(html: str) -> str:
    if not html or not html.strip():
        return html
    html = html.strip()
    soup = BeautifulSoup(html, "html.parser")
    firsttext = soup.find(string=True)
    if firsttext and firsttext.strip():
        firsttext.replace_with(safe_re_sub(r'^\s+', '', firsttext, count=1))
    result = str(soup).strip()
    return result

def split_html_to_paragraphs(html_text):
    html_text = html_text.strip()
    if not html_text:
        return []
    result = []
    cursor = 0
    for m in re.finditer(r'<p[^>]*>.*?</p>', html_text, re.DOTALL | re.IGNORECASE):
        gap = html_text[cursor:m.start()].strip()
        if gap:
            result.append(gap)
        result.append(m.group(0).strip())
        cursor = m.end()
    tail = html_text[cursor:].strip()
    if tail:
        result.append(tail)
    if not result:
        return [html_text] if html_text.strip() else []
    return [r for r in result if r.strip()]

def split_html_by_leading_number(html_str, numbers):
    if not html_str or not numbers:
        return {}
    paragraphs = re.findall(r'<p[^>]*>.*?</p>', html_str, re.DOTALL | re.IGNORECASE)
    if not paragraphs:
        blocks = re.split(r'\n\s*\n', html_str.strip())
        if blocks:
            paragraphs = [f'<p>{b.strip()}</p>' for b in blocks if b.strip()]
        else:
            paragraphs = [f'<p>{html_str.strip()}</p>'] if html_str.strip() else []
    if not paragraphs:
        return {}
    all_markers = []
    for idx, para in enumerate(paragraphs):
        text = safe_re_sub(r'<[^>]+>', '', para)
        text = safe_re_sub(r'&nbsp;', ' ', text)
        text = safe_re_sub(r'^[«»"\'‘’“”\s]+', '', text).strip()
        m = re.match(r'^(\d+(?:\.\d+)?[\.\)]|[а-яё][\.\)])\s', text)
        if m:
            marker_norm = re.sub(r'[\.\)]$', '', m.group(1))
            all_markers.append((marker_norm, idx))
    if not all_markers:
        return {numbers[0]: html_str}
    all_markers.sort(key=lambda x: x[1])
    result = {}
    requested = {n.rstrip('.)') for n in numbers}
    for i, (marker, idx) in enumerate(all_markers):
        start = idx
        end = all_markers[i + 1][1] if i + 1 < len(all_markers) else len(paragraphs)
        fragment = '\n'.join(paragraphs[start:end]).strip()
        if marker in requested:
            result[marker] = fragment
    return result

def build_search_pattern(original_data):
    doc_type = original_data.get('doc_type', original_data.get('npa_type', 'law'))
    npa_number = original_data.get('npa_number', '')
    clean_number = safe_re_sub(r'[^0-9]', '', npa_number)
    if doc_type == 'law':
        return rf'(?i)(закон[а-я]*)?\s*№\s*{clean_number}', clean_number
    date_str = original_data.get('date_passed', '') or original_data.get('date_reg', '')
    if not date_str:
        return rf'(?i)постановление[а-я]*\s+Законодательного\ Собрания\ города\ Севастополя\s+№\s*{clean_number}', clean_number
    try:
        day, month, year = date_str.split('.')
        months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        month_name = months[int(month) - 1]
        date_pattern = rf'от\s+{int(day)}\s+{month_name}\s+{year}\s+года'
    except (ValueError, IndexError):
        date_pattern = ''
    if date_pattern:
        pattern = rf'(?i)(постановление[а-я]*)\s+Законодательного\ Собрания\ города\ Севастополя\s+{date_pattern}\s+№\s*{clean_number}'
    else:
        pattern = rf'(?i)(постановление[а-я]*)\s+Законодательного\ Собрания\ города\ Севастополя\s+№\s*{clean_number}'
    return pattern, clean_number

def get_clean_text_from_block(block):
    raw = block.get('html_text', block.get('text', ''))
    if not raw:
        return ''
    clean = safe_re_sub(r'<[^>]+>', '', raw)
    clean = ' '.join(clean.split())
    return clean

def strip_number_from_element_html(html: str, item_number: str, item_type: str) -> str:
    if not html or not item_number or item_type not in ('part', 'point', 'subpoint'):
        return html
    item_number = str(item_number)
    item_num_clean = item_number.strip().rstrip('.)')
    pattern = r'^\s*(<p[^>]*>)\s*' + re.escape(item_num_clean) + r'[\.\)]?\s*'
    cleaned = safe_re_sub(pattern, r'\1', html, count=1, flags=re.DOTALL)
    return cleaned


def _correct_table_highlights(old_html, new_html, highlights, log_callback=None):
    if not highlights or not isinstance(highlights, dict):
        return highlights

    try:
        old_soup = BeautifulSoup(old_html, 'html.parser')
        new_soup = BeautifulSoup(new_html, 'html.parser')

        old_rows = old_soup.find_all('tr')
        new_rows = new_soup.find_all('tr')

        if not old_rows or not new_rows:
            return highlights

        # Сравниваем именно HTML-код строк, чтобы заметить даже изменение тегов
        old_strs = [str(r).strip() for r in old_rows]
        new_strs = [str(r).strip() for r in new_rows]

        # SequenceMatcher умно находит изменившиеся блоки, не путая их со сдвигом
        sm = difflib.SequenceMatcher(None, old_strs, new_strs)

        diff_prev = []
        diff_curr = []
        additions = []
        deletions = []

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                continue
            elif tag == 'replace':
                # Произошла замена строк (старые i1..i2 на новые j1..j2)
                old_range = list(range(i1, i2))
                new_range = list(range(j1, j2))
                # Сохраняем попарную сортировку
                for k in range(max(len(old_range), len(new_range))):
                    o_idx = old_range[k] if k < len(old_range) else None
                    n_idx = new_range[k] if k < len(new_range) else None
                    if o_idx is not None and n_idx is not None:
                        diff_prev.append(["table", str(o_idx + 1)])
                        diff_curr.append(["table", str(n_idx + 1)])
                    elif o_idx is not None:
                        deletions.append(["table", str(o_idx + 1)])
                    elif n_idx is not None:
                        additions.append(["table", str(n_idx + 1)])
            elif tag == 'delete':
                # Строки были удалены
                for k in range(i1, i2):
                    deletions.append(["table", str(k + 1)])
            elif tag == 'insert':
                # Строки были добавлены
                for k in range(j1, j2):
                    additions.append(["table", str(k + 1)])

        # Если программа вообще не нашла изменений, оставляем ответ агента этапа 4 (он может быть прав)
        if not diff_prev and not diff_curr and not additions and not deletions:
            if log_callback:
                log_callback("  Корректировка: изменений в HTML строк не найдено, оставлен ответ агента этапа 4.", 'info')
            return highlights

        if log_callback:
            log_callback(f"  Корректировка подсветки: замен={len(diff_prev)}, доб={len(additions)}, уд={len(deletions)}", 'info')

        return {
            "previous_edition": {
                "deletion": deletions,
                "addition": [],
                "difference": diff_prev
            },
            "current_edition": {
                "deletion": [],
                "addition": additions,
                "difference": diff_curr
            }
        }
    except Exception as e:
        # Если в программе произошла ошибка, безопасно возвращаем ответ агента этапа 4
        if log_callback:
            log_callback(f"  Ошибка при программной корректировке подсветки: {e}. Оставлен ответ агента этапа 4.", 'warning')
        return highlights

def parse_stage4_answer(response_text, change_description="", log_callback=None):
    from npa_processor.processing.element_ops import _normalize_highlights_positions
    if not response_text:
        return "", None
    response_text = strip_thinking_tags(response_text)
    response_text = response_text.strip()
    if response_text.startswith('```json') and response_text.endswith('```'):
        response_text = response_text[7:-3].strip()
    elif response_text.startswith('```') and response_text.endswith('```'):
        response_text = response_text[3:-3].strip()
    try:
        data = json.loads(response_text)
        if not isinstance(data, dict):
            if log_callback:
                log_callback(f"  Ответ агента этапа 4 распознан как {type(data).__name__}, не dict — используется как HTML", 'warning')
            return str(data), None
        html = data.get('html', '')
        highlights = data.get('highlights', None)
        html = safe_re_sub(r'  +', ' ', html)
        html = safe_re_sub(r';{2,}', ';', html)
        highlights = _normalize_highlights_positions(highlights)
        return html, highlights
    except json.JSONDecodeError:
        if log_callback:
            log_callback("  Ответ агента этапа 4 не является JSON, используется как чистый HTML", 'warning')
        return response_text, None

def add_number_to_paragraph_html(html_text, item_number, item_type):
    if not html_text or not item_number or item_type not in ('part', 'point', 'subpoint'):
        return html_text
    item_number = str(item_number)
    formatted_num = f"{item_number}." if item_type in ('part', 'point') else item_number.rstrip('.') + ')'
    soup = BeautifulSoup(html_text, 'html.parser')
    first_para = soup.find(['p', 'div'])
    if not first_para:
        return f"{formatted_num} {html_text}"
    para_text = first_para.get_text(strip=True)
    if re.match(r'^' + re.escape(formatted_num) + r'[\s\.\)]', para_text):
        return html_text
    original_content = first_para.decode_contents()
    first_para.clear()
    first_para.append(f"{formatted_num} {original_content}")
    return str(soup)

def parse_structural_tokens(structural):
    if not structural:
        return []
    structural = safe_re_sub(r'[\s\xa0\u2000-\u200F\u2028\u202F\u3000]+', ' ', structural)
    tokens = []
    structural_lower = structural.lower()
    parts = structural_lower.split()
    i = 0
    while i < len(parts):
        word = parts[i]
        found_type = None
        for eng, rus in TYPE_TO_RUSSIAN.items():
            if rus.lower() == word:
                found_type = eng
                break
        if not found_type:
            if 'стат' in word:
                found_type = 'article'
            elif 'част' in word:
                found_type = 'part'
            elif 'подпункт' in word:
                found_type = 'subpoint'
            elif 'пункт' in word:
                found_type = 'point'
            elif 'абзац' in word:
                found_type = 'paragraph'
            elif 'глав' in word:
                found_type = 'chapter'
            elif 'раздел' in word:
                found_type = 'section'
            elif 'приложен' in word:
                found_type = 'appendix'
            elif 'преамбул' in word:
                found_type = 'preamble'
            elif 'таблиц' in word:
                found_type = 'structured_table'
        if not found_type:
            i += 1
            continue
        num = None
        _ROMAN_RE = re.compile(r'^[IVXLCDM]+[⁰¹²³⁴⁵⁶⁷⁸⁹]*$', re.IGNORECASE)
        if i + 1 < len(parts):
            cand = parts[i+1]
            cand_clean = cand.rstrip('.,;:)')
            cand_clean = cand_clean.strip('«»\u201c\u201d\u2018\u2019"\'')
            cand_clean = cand_clean.rstrip('.,;:)')
            if (cand_clean.isdigit()
                    or ('.' in cand_clean and cand_clean.replace('.', '').isdigit())
                    or re.match(r'^[а-я]$', cand_clean)
                    or _ROMAN_RE.match(cand_clean)):
                if _ROMAN_RE.match(cand_clean):
                    roman_letters = re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹]', '', cand_clean).upper()
                    indices = re.sub(r'[^⁰¹²³⁴⁵⁶⁷⁸⁹]', '', cand_clean)
                    num = roman_letters + indices
                else:
                    num = cand_clean
                i += 1
        tokens.append((found_type, num))
        i += 1
    return tokens

def format_structural_number(number, is_header=False, has_title=False):
    if not number:
        return ""
    clean_num = str(number).strip()
    if is_header:
        if has_title:
            return f"{clean_num}." if not clean_num.endswith('.') else clean_num
        else:
            return clean_num.rstrip('.')
    else:
        if clean_num.endswith(')'):
            return clean_num
        return f"{clean_num}." if not clean_num.endswith('.') else clean_num

def get_item_html_recursive(item, all_items_map, include_header=True):
    item_type = item.get('item_type', '')
    number = item.get('item_number', '')
    item.get('item_id', '')
    html_out = ""
    if include_header and item_type in ('article', 'chapter', 'section', 'appendix'):
        type_rus = TYPE_TO_RUSSIAN.get(item_type, item_type).capitalize()
        head_text = ""
        if item.get('head_revisions'):
            for hr in reversed(item['head_revisions']):
                if hr.get('valid_to') is None:
                    head_text = hr.get('head_text', '').strip()
                    break
        if item_type == 'appendix':
            prefix_text = get_active_prefix_text(item)
            if prefix_text:
                html_out += f"{prefix_text}\n"
            else:
                formatted_num = format_structural_number(number, is_header=True, has_title=bool(head_text))
                header_content = f"{type_rus} {formatted_num}"
                if head_text:
                    header_content += f" {head_text}"
                html_out += f"<p><b>{header_content}</b></p>\n"
        else:
            formatted_num = format_structural_number(number, is_header=True, has_title=bool(head_text))
            header_content = f"{type_rus} {formatted_num}"
            if head_text:
                header_content += f" {head_text}"
            html_out += f"<p><b>{header_content}</b></p>\n"
    active_body = []
    if item.get('revisions'):
        for rev in reversed(item['revisions']):
            if rev.get('valid_to') is None:
                active_body = copy.deepcopy(rev.get('body', []))
                break
    if item_type in ('part', 'point', 'subpoint'):
        formatted_num = format_structural_number(number, is_header=False)
        found_paragraph = False
        for block in active_body:
            if block.get('type') == 'paragraph':
                orig_text = block.get('html_text', '')
                match = re.match(r'(<p[^>]*>)(.*)', orig_text, re.IGNORECASE | re.DOTALL)
                if match:
                    block['html_text'] = f"{match.group(1)}{formatted_num} {match.group(2)}"
                else:
                    block['html_text'] = f"{formatted_num} {orig_text}"
                found_paragraph = True
                break
        if not found_paragraph:
            active_body.insert(0, {'type': 'paragraph', 'html_text': f"{formatted_num} ", 'order': 1})
    for block in active_body:
        b_type = block.get('type')
        if b_type == 'paragraph' or b_type == 'table_fragment' or b_type == 'table_header':
            html_out += block.get('html_text', '') + "\n"
        elif b_type == 'child_ref':
            child_id = block.get('item_id')
            child_item = None
            if item.get('item_children'):
                child_item = next((c for c in item['item_children'] if c['item_id'] == child_id), None)
            if child_item:
                html_out += get_item_html_recursive(child_item, all_items_map)
    return html_out

def extract_html_from_element(element, include_number=True):
    return get_item_html_recursive(element, {})

def get_full_element_html(element, use_original_structure=False, include_number=True, include_header=True):
    if not element:
        return ""
    return get_item_html_recursive(element, {}, include_header=include_header)

def extract_text_from_revision(rev):
    text = ''
    for block in rev.get('body', []):
        if block.get('type') == 'paragraph':
            html = block.get('html_text', '')
            clean = safe_re_sub(r'<[^>]+>', '', html)
            text += clean + ' '
    return text.strip()

def extract_text_from_element(element):
    from npa_processor.processing.text_utils import get_active_revision
    rev = get_active_revision(element)
    text = extract_text_from_revision(rev) if rev else ''
    for child in element.get('item_children', []):
        text += ' ' + extract_text_from_element(child)
    return text

def get_active_prefix_text(element):
    if element.get('item_type') != 'appendix':
        return None
    prefix_revs = element.get('item_prefix_revisions', [])
    for rev in reversed(prefix_revs):
        if rev.get('valid_to') is None:
            return rev.get('prefix_text', '')
    if prefix_revs:
        return prefix_revs[-1].get('prefix_text', '')
    return None

def get_current_head(element):
    head_revisions = element.get('head_revisions', [])
    for rev in reversed(head_revisions):
        if rev.get('valid_to') in (None, ''):
            return rev.get('head_text', '')
    if head_revisions:
        return head_revisions[-1].get('head_text', '')
    revisions = element.get('revisions', [])
    if not revisions:
        return ''
    for rev in reversed(revisions):
        if rev.get('valid_to') in (None, ''):
            return rev.get('item_head', '')
    return revisions[-1].get('item_head', '')

def create_element_skeleton(item_type, item_number, html_text, parent_id, existing_ids, id_counter, item_level,
                           valid_from=None, modified_by_id=None, mod_type=None, doc_id=None):
    clean_num = str(clean_number(str(item_number))).replace('.', '_')
    clean_parent_id = parent_id.rstrip('_') if parent_id else ''
    if clean_parent_id:
        base_id = f"{clean_parent_id}_{item_type}_{clean_num}"
    else:
        base_id = f"{doc_id}_{item_type}_{clean_num}" if doc_id else f"toc_{item_type}_{clean_num}"
    base_id = safe_re_sub(r'_+', '_', base_id).rstrip('_')
    candidate_id = base_id
    suffix = 2
    while candidate_id in existing_ids:
        candidate_id = f"{base_id}_{suffix}"
        suffix += 1
    existing_ids.add(candidate_id)
    id_counter[0] += 1
    element = {
        'item_id': candidate_id,
        'item_type': item_type,
        'item_number': str(item_number),
        'item_level': item_level,
        'item_children': []
    }
    if item_type in ('article', 'chapter', 'section', 'appendix'):
        element['head_revisions'] = []
    if item_type == 'appendix':
        element['item_prefix_revisions'] = []
    if valid_from is not None:
        body = []
        if html_text:
            if isinstance(html_text, list):
                for idx, t in enumerate(html_text, 1):
                    body.append({'type': 'paragraph', 'html_text': t, 'order': idx})
            else:
                body.append({'type': 'paragraph', 'html_text': html_text, 'order': 1})
        rev = {'body': body}
        if mod_type:
            rev['mod_type'] = mod_type
        if valid_from:
            rev['valid_from'] = valid_from
        if modified_by_id:
            rev['modified_by_id'] = modified_by_id
        element['revisions'] = [rev]
    else:
        body = []
        if html_text:
            if isinstance(html_text, list):
                for idx, t in enumerate(html_text, 1):
                    body.append({'type': 'paragraph', 'html_text': t, 'order': idx})
            else:
                body.append({'type': 'paragraph', 'html_text': html_text, 'order': 1})
        element['revisions'] = [{'body': body}]
    return element


def _extract_replacement_pairs(description):
    if not description:
        return []
    pairs = []
    patterns = [
        r'заменить\s+(?:слова(?:ми)?\s+)?[«"]([^»"]+)[»"]\s+(?:на\s+)?(?:слова(?:ми)?\s+)?[«"]([^»"]+)[»"]',
        r'слова(?:ми)?\s+[«"]([^»"]+)[»"]\s+заменить\s+(?:на\s+)?(?:слова(?:ми)?\s+)?[«"]([^»"]+)[»"]',
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, description, re.IGNORECASE):
            old_text = m.group(1).strip()
            new_text = m.group(2).strip()
            if old_text and new_text and old_text != new_text:
                pairs.append((old_text, new_text))
    return pairs


def _deduplicate_highlights(highlights):
    if not highlights or not isinstance(highlights, dict):
        return highlights
    for side in ("previous_edition", "current_edition"):
        for cat in ("deletion", "addition", "difference"):
            if cat not in highlights.get(side, {}):
                continue
            seen = set()
            deduped = []
            for entry in highlights[side][cat]:
                if isinstance(entry, dict):
                    text = entry.get("text", "")
                    pos = str(entry.get("positions", ""))
                elif isinstance(entry, list) and len(entry) >= 2:
                    text = entry[0]
                    pos = str(entry[1])
                else:
                    continue
                key = (text, pos)
                if key not in seen:
                    seen.add(key)
                    deduped.append(entry)
            highlights[side][cat] = deduped
    return highlights


def _normalize_for_comparison(text):
    if not text:
        return ""
    return ' '.join(text.split())


def _verify_highlights_for_replacements(highlights, replacement_pairs):
    if not highlights or not isinstance(highlights, dict):
        return False
    if not replacement_pairs:
        return True

    prev_texts = set()
    curr_texts = set()
    for side, target in (("previous_edition", prev_texts), ("current_edition", curr_texts)):
        for cat in ("deletion", "addition", "difference"):
            for entry in highlights.get(side, {}).get(cat, []):
                if isinstance(entry, dict):
                    text = entry.get("text", "")
                elif isinstance(entry, list) and len(entry) >= 1:
                    text = entry[0]
                else:
                    continue
                target.add(_normalize_for_comparison(text))

    for old_text, new_text in replacement_pairs:
        old_norm = _normalize_for_comparison(old_text)
        new_norm = _normalize_for_comparison(new_text)
        if old_norm not in prev_texts or new_norm not in curr_texts:
            return False
    return True


def compute_highlights_from_html_diff(old_html, new_html, log_callback=None, change_description=None):
    if not old_html and not new_html:
        return None
    if not old_html:
        return {
            "previous_edition": {"deletion": [], "addition": [], "difference": []},
            "current_edition": {"deletion": [], "addition": [["", "1-all"]], "difference": []}
        }
    if not new_html:
        return {
            "previous_edition": {"deletion": [["", "1-all"]], "addition": [], "difference": []},
            "current_edition": {"deletion": [], "addition": [], "difference": []}
        }

    def split_paragraphs(html):
        soup = BeautifulSoup(html, 'html.parser')
        paragraphs = []
        for p in soup.find_all('p'):
            text = ' '.join(p.get_text(separator=' ', strip=True).split())
            if text:
                paragraphs.append(text)
        if not paragraphs:
            text = ' '.join(soup.get_text(separator=' ', strip=True).split())
            if text:
                paragraphs = [text]
        return paragraphs


    replacement_pairs = _extract_replacement_pairs(change_description) if change_description else []

    old_paras = split_paragraphs(old_html)
    new_paras = split_paragraphs(new_html)

    if not old_paras and not new_paras:
        return None

    highlights = {
        "previous_edition": {"deletion": [], "addition": [], "difference": []},
        "current_edition": {"deletion": [], "addition": [], "difference": []}
    }

    max_paras = max(len(old_paras), len(new_paras))
    for para_idx in range(max_paras):
        old_text = old_paras[para_idx] if para_idx < len(old_paras) else ""
        new_text = new_paras[para_idx] if para_idx < len(new_paras) else ""

        if old_text == new_text:
            continue

        if not old_text:
            highlights["current_edition"]["addition"].append([new_text, f"{para_idx + 1}-all"])
            continue
        if not new_text:
            highlights["previous_edition"]["deletion"].append([old_text, f"{para_idx + 1}-all"])
            continue

        para_pairs = []
        for old_block, new_block in replacement_pairs:
            if old_block in old_text or new_block in new_text:
                para_pairs.append((old_block, new_block))

        counter = 1
        handled_by_replacement = False
        if para_pairs:
            old_masked = old_text
            new_masked = new_text
            for old_block, new_block in para_pairs:
                old_occs = []
                start = 0
                while True:
                    idx = old_text.find(old_block, start)
                    if idx == -1:
                        break
                    old_occs.append(idx)
                    start = idx + len(old_block)

                new_occs = []
                start = 0
                while True:
                    idx = new_text.find(new_block, start)
                    if idx == -1:
                        break
                    new_occs.append(idx)
                    start = idx + len(new_block)

                pair_count = min(len(old_occs), len(new_occs))
                for _ in range(pair_count):
                    highlights["previous_edition"]["difference"].append([old_block, f"{para_idx + 1}-{counter}"])
                    highlights["current_edition"]["difference"].append([new_block, f"{para_idx + 1}-{counter}"])
                    counter += 1

                old_masked = old_masked.replace(old_block, ' ' * len(old_block))
                new_masked = new_masked.replace(new_block, ' ' * len(new_block))

            if old_text != old_masked or new_text != new_masked:
                handled_by_replacement = True
            old_text = old_masked
            new_text = new_masked

        if not handled_by_replacement and old_text != new_text:
            def longest_common_prefix(a, b):
                i = 0
                while i < len(a) and i < len(b) and a[i] == b[i]:
                    i += 1
                return i

            def longest_common_suffix(a, b):
                i = 1
                while i <= len(a) and i <= len(b) and a[-i] == b[-i]:
                    i += 1
                return i - 1

            prefix_len = longest_common_prefix(old_text, new_text)
            suffix_len = longest_common_suffix(old_text[prefix_len:], new_text[prefix_len:])
            old_middle = old_text[prefix_len:len(old_text) - suffix_len] if prefix_len < len(old_text) - suffix_len else ""
            new_middle = new_text[prefix_len:len(new_text) - suffix_len] if prefix_len < len(new_text) - suffix_len else ""

            if old_middle and new_middle:
                highlights["previous_edition"]["difference"].append([old_middle, f"{para_idx + 1}-{counter}"])
                highlights["current_edition"]["difference"].append([new_middle, f"{para_idx + 1}-{counter}"])
                counter += 1
            elif new_middle:
                highlights["current_edition"]["addition"].append([new_middle, f"{para_idx + 1}-{counter}"])
                counter += 1
            elif old_middle:
                highlights["previous_edition"]["deletion"].append([old_middle, f"{para_idx + 1}-{counter}"])
                counter += 1

    highlights = _deduplicate_highlights(highlights)

    empty = True
    for side in ("previous_edition", "current_edition"):
        for cat in ("deletion", "addition", "difference"):
            if highlights[side][cat]:
                empty = False
                break
        if not empty:
            break
    if empty:
        return None

    if log_callback:
        log_callback(f"  Подсветка: удалений={len(highlights['previous_edition']['deletion'])}, добавлений={len(highlights['current_edition']['addition'])}, изменений={len(highlights['previous_edition']['difference'])}", 'result')
    return highlights
