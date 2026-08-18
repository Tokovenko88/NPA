"""Текстовые утилиты для обработки НПА."""

import re
from bs4 import BeautifulSoup


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def strip_thinking_tags(text):
    if not text:
        return text
    text = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>\s*', '', text, flags=re.DOTALL | re.IGNORECASE)
    if re.search(r'</think(?:ing)?>', text, re.IGNORECASE):
        text = re.sub(r'^.*?</think(?:ing)?>\s*', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<think(?:ing)?>.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def sup_digits_to_unicode(text):
    if not text:
        return ""
    sup_digits = str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹')
    def replacer(match):
        digits = match.group(1).strip()
        return digits.translate(sup_digits)
    return re.sub(r'<sup>\s*([0-9]+)\s*</sup>', replacer, text, flags=re.IGNORECASE)


def safe_re_sub(pattern, repl, string, *args, **kwargs):
    if not isinstance(pattern, (str, bytes)) and not hasattr(pattern, 'match'):
        pattern = str(pattern) if pattern is not None else ""
    if not isinstance(repl, (str, bytes)) and not callable(repl):
        repl = str(repl) if repl is not None else ""
    if not isinstance(string, (str, bytes)):
        string = str(string) if string is not None else ""
    return re.sub(pattern, repl, string, *args, **kwargs)


def normalize_number_string(num_str: str) -> str:
    if not num_str:
        return ""
    num_str = str(num_str).strip()
    num_str = sup_digits_to_unicode(num_str)
    num_str = re.sub(r'<[^>]+>', '', num_str)
    num_str = num_str.strip()
    roman_with_sup_pattern = re.compile(r'^[IVXLCDMivxlcdm]+([⁰¹²³⁴⁵⁶⁷⁸⁹]*)$')
    match = roman_with_sup_pattern.match(num_str)
    if match:
        roman_part = re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹]', '', num_str).upper()
        suffix_part = match.group(1)
        return roman_part + suffix_part
    return num_str


def clean_head_text(head_text: str, item_type: str, item_number: str) -> str:
    if not head_text:
        return head_text
    head_text = safe_re_sub(r'<[^>]+>', ' ', head_text)
    head_text = head_text.replace('&laquo;', '«').replace('&raquo;', '»')
    head_text = head_text.replace('&nbsp;', ' ').replace('&amp;', '&')
    head_text = head_text.replace('&lt;', '<').replace('&gt;', '>')
    head_text = ' '.join(head_text.split())
    head_text = head_text.lstrip('«»"\'“” \t\n\r')
    if item_type not in ('article', 'chapter', 'section', 'appendix'):
        return head_text.strip()
    type_word = {
        'article': 'Статья',
        'chapter': 'Глава',
        'section': 'Раздел',
        'appendix': 'Приложение'
    }.get(item_type, '')
    if not type_word:
        return head_text.strip()
    if item_number:
        num_pattern = re.escape(str(item_number)) + r'(?:[.\-–—]\d+)*'
    else:
        num_pattern = r'[0-9A-Za-zА-Яа-яБё.\-–—]+'
    pattern = re.compile(
        r'^' + re.escape(type_word) +
        r'\s*(?:N|№)?\s*' +
        num_pattern +
        r'\s*[.,;:·\-–—]?\s*',
        re.IGNORECASE
    )
    cleaned = pattern.sub('', head_text).strip()
    return cleaned


def normalize_item_number(item_type, number):
    if not number:
        return number
    number = str(number).strip()
    number = number.strip('«»“”‘’"\'')
    number = number.strip()
    if item_type in ('point', 'subpoint'):
        if not number.endswith(')'):
            return number + ')'
    return number


def normalize_text_for_search(text):
    if not text:
        return ''
    text = safe_re_sub(r'[\s\xa0\u2000-\u200F\u2028\u202F\u205F\u3000]+', ' ', text)
    text = safe_re_sub(r'[^\w\s]', '', text)
    text = text.lower().strip()
    return text


# ===== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ПРОВЕРКИ ОКОНЧАНИЯ ЭЛЕМЕНТА =====

def _ends_with(element, char):
    if not element:
        return False
    rev = get_active_revision(element)
    if not rev:
        return False
    body = rev.get('body', [])
    for block in reversed(body):
        if block.get('type') == 'paragraph':
            html = block.get('html_text', '')
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                text = soup.get_text()
                text = text.strip()
                if text.endswith(char):
                    return True
    return False


# ===== ОСНОВНЫЕ ФУНКЦИИ КОРРЕКТИРОВКИ ПУНКТУАЦИИ =====

def adjust_last_item_punctuation(parent, new_item, log_callback=None, rebuild_ids=None):
    if not parent or not new_item:
        return
    children = parent.get('item_children', [])
    if not children:
        return

    same_type = [c for c in children if c.get('item_type') == new_item.get('item_type')]
    if len(same_type) <= 1:
        return

    def sort_key(item):
        num = item.get('item_number', '')
        if num is None:
            num = ''
        num = str(num)
        clean = safe_re_sub(r'[.)]$', '', num)
        try:
            return int(clean)
        except ValueError:
            return 0

    same_type.sort(key=sort_key)
    try:
        idx = same_type.index(new_item)
    except ValueError:
        return

    if idx != len(same_type) - 1:
        return

    prev_item = same_type[idx - 1]

    other_items = [c for c in same_type if c.get('item_id') != new_item.get('item_id')]
    has_semicolon = any(_ends_with(c, ';') for c in other_items)

    if not has_semicolon:
        if log_callback:
            log_callback(
                f"  Техническая правка не требуется: все сестринские элементы заканчиваются точкой",
                'info'
            )
        return

    if _ends_with(prev_item, ';'):
        return

    revisions = prev_item.get('revisions', [])
    active_rev = None
    for rev in reversed(revisions):
        if rev.get('valid_to') is None:
            active_rev = rev
            break
    if not active_rev:
        if log_callback:
            log_callback(
                f"  Не найдена активная ревизия для элемента {prev_item.get('item_id')}",
                'warning'
            )
        return

    body = active_rev.get('body', [])
    last_para = None
    for block in reversed(body):
        if block.get('type') == 'paragraph':
            last_para = block
            break
    if not last_para:
        return

    html = last_para.get('html_text', '')
    if not html:
        return

    if html.rstrip().endswith('.</p>'):
        new_html = html.rstrip()[:-5] + ';</p>'
        last_para['html_text'] = new_html
        if log_callback:
            log_callback(
                f"  Техническая правка: у пункта {prev_item.get('item_number')} точка заменена на точку с запятой",
                'info'
            )
    else:
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text()
        if text.endswith('.'):
            last_dot = html.rfind('.')
            if last_dot != -1:
                new_html = html[:last_dot] + ';' + html[last_dot+1:]
                last_para['html_text'] = new_html
                if log_callback:
                    log_callback(
                        f"  Техническая правка: у пункта {prev_item.get('item_number')} точка заменена на точку с запятой",
                        'info'
                    )


def adjust_punctuation_after_deletion(parent, deleted_item, log_callback=None):
    if not parent or not deleted_item:
        return
    children = parent.get('item_children', [])
    if not children:
        return

    same_type = [c for c in children if c.get('item_type') == deleted_item.get('item_type')]
    if len(same_type) <= 1:
        return

    def sort_key(item):
        num = item.get('item_number', '')
        num = str(num)
        clean = safe_re_sub(r'[.)]$', '', num)
        try:
            return int(clean)
        except ValueError:
            return 0

    same_type.sort(key=sort_key)
    try:
        idx = same_type.index(deleted_item)
    except ValueError:
        return

    if idx != len(same_type) - 1:
        return

    new_last = same_type[idx - 1] if idx > 0 else None
    if not new_last:
        return

    if not _ends_with(new_last, ';'):
        return

    revisions = new_last.get('revisions', [])
    active_rev = None
    for rev in reversed(revisions):
        if rev.get('valid_to') is None:
            active_rev = rev
            break
    if not active_rev:
        if log_callback:
            log_callback(
                f"  Не найдена активная ревизия для элемента {new_last.get('item_id')}",
                'warning'
            )
        return

    body = active_rev.get('body', [])
    last_para = None
    for block in reversed(body):
        if block.get('type') == 'paragraph':
            last_para = block
            break
    if not last_para:
        return

    html = last_para.get('html_text', '')
    if not html:
        return

    if html.rstrip().endswith(';</p>'):
        new_html = html.rstrip()[:-5] + '.</p>'
        last_para['html_text'] = new_html
        if log_callback:
            log_callback(
                f"  Техническая правка: у пункта {new_last.get('item_number')} точка с запятой заменена на точку",
                'info'
            )
    else:
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text()
        if text.endswith(';'):
            last_semicolon = html.rfind(';')
            if last_semicolon != -1:
                new_html = html[:last_semicolon] + '.' + html[last_semicolon+1:]
                last_para['html_text'] = new_html
                if log_callback:
                    log_callback(
                        f"  Техническая правка: у пункта {new_last.get('item_number')} точка с запятой заменена на точку",
                        'info'
                    )


# ===== ОСТАЛЬНЫЕ УТИЛИТЫ =====

def normalize_structural(s):
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    s = s.lower()
    replacements = {
        r'\bстатьи\b': 'статья',
        r'\bчасти\b': 'часть',
        r'\bпункта\b': 'пункт',
        r'\bподпункта\b': 'подпункт',
        r'\bабзаца\b': 'абзац',
        r'\bглавы\b': 'глава',
        r'\bраздела\b': 'раздел',
        r'\bприложения\b': 'приложение',
    }
    for pattern, repl in replacements.items():
        s = safe_re_sub(pattern, repl, s)
    return s


def parse_num(s):
    if not s:
        return (0,)
    if isinstance(s, (int, float)):
        return (int(s),)
    parts = str(s).split('.')
    result = []
    for p in parts:
        p = p.rstrip(')')
        if p.isdigit():
            result.append(int(p))
    return tuple(result) if result else (0,)


def clean_html_text(html):
    if not html:
        return ''
    text = safe_re_sub(r'<[^>]+>', '', html)
    return ' '.join(text.split())


def get_active_revision(element, use_original=False):
    revisions = element.get('revisions', [])
    if not revisions:
        return None
    if use_original:
        for rev in reversed(revisions):
            body = rev.get('body', [])
            if any(b.get('type') == 'child_ref' for b in body):
                return rev
        for rev in reversed(revisions):
            if rev.get('valid_to') in (None, ''):
                return rev
        return revisions[-1]
    else:
        for rev in reversed(revisions):
            if rev.get('valid_to') in (None, ''):
                return rev
        return revisions[-1] if revisions else None


def get_element_text(element):
    rev = get_active_revision(element)
    if not rev:
        return ''
    text = ''
    for block in rev.get('body', []):
        if block.get('type') == 'paragraph':
            html = block.get('html_text', '')
            clean = safe_re_sub(r'<[^>]+>', '', html)
            text += clean + ' '
    return ' '.join(text.split())


def shift_highlight_index(pos_str, threshold, delta):
    try:
        if '-' not in pos_str:
            return pos_str
        p_num_str, p_suffix = pos_str.split('-', 1)
        p_num = int(p_num_str)
        if p_num >= threshold:
            return f"{p_num + delta}-{p_suffix}"
    except (ValueError, IndexError):
        pass
    return pos_str


def clean_number(num_str):
    if num_str is None:
        return ""
    original = str(num_str).strip()
    original = normalize_number_string(original)
    if re.match(r'^[IVXLCDM]+$', original.upper()):
        roman = original.upper()
        values = {'I':1, 'V':5, 'X':10, 'L':50, 'C':100, 'D':500, 'M':1000}
        total = 0
        prev = 0
        for ch in reversed(roman):
            val = values.get(ch, 0)
            if val < prev:
                total -= val
            else:
                total += val
            prev = val
        return total
    cleaned = safe_re_sub(r'[«»"\'s\(,;:]', '', original)
    cleaned = cleaned.rstrip('.)')
    cleaned = cleaned.lower().strip()
    latin_to_cyrillic = {
        'a': 'а', 'e': 'е', 'y': 'у', 'c': 'с', 'o': 'о', 'p': 'р', 'x': 'х',
        'k': 'к', 'm': 'м', 't': 'т', 'b': 'б', 'h': 'н', 'i': 'и', 'j': 'й',
        'u': 'у', 'f': 'ф', 'g': 'г', 'd': 'д', 'l': 'л', 'n': 'н', 'r': 'р',
        's': 'с', 'v': 'в', 'z': 'з', 'w': 'в', 'q': 'к'
    }
    cleaned = ''.join(latin_to_cyrillic.get(ch, ch) for ch in cleaned)
    cleaned = safe_re_sub(r'[\x00-\x1f\x7f\u2000-\u200f\u2028-\u202f]', '', cleaned)
    cleaned = ' '.join(cleaned.split())
    try:
        if cleaned.isdigit():
            return int(cleaned)
        return cleaned
    except ValueError:
        return cleaned
