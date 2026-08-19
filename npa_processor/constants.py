import os

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(os.path.dirname(CONFIG_DIR), 'prompts')

DEFAULT_EXTRA_OPTIONS = {
    "temperature": 0.0,
    "top_p": 0.1,
}

TYPE_TO_RUSSIAN = {
    'article': 'Статья',
    'part': 'Часть',
    'point': 'Пункт',
    'subpoint': 'Подпункт',
    'chapter': 'Глава',
    'section': 'Раздел',
    'appendix': 'Приложение',
    'paragraph': 'Абзац',
    'preamble': 'Преамбула',
    'structured_table': 'Таблица',
}

PLURAL_TO_SINGULAR = {
    'части': 'часть',
    'пункты': 'пункт',
    'подпункты': 'подпункт',
    'статьи': 'статья',
    'главы': 'глава',
    'разделы': 'раздел',
    'приложения': 'приложение',
}


def _resolve_prompt_path(filename):
    candidates = [
        os.path.join(PROMPTS_DIR, filename),
        os.path.join(CONFIG_DIR, 'prompts', filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def load_prompt_from_file(filename):
    path = _resolve_prompt_path(filename)
    if path is None:
        return ""
    with open(path, encoding='utf-8') as f:
        return f.read()


_prompt_cache = {}


def get_prompt(name: str) -> str:
    for ext in ('.md', '.txt'):
        content = load_prompt_from_file(f'{name}{ext}')
        if content:
            return content
    return ""
