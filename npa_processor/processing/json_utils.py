"""JSON-утилиты: загрузка, сохранение."""

import json
import os

from npa_processor.processing.text_utils import strip_thinking_tags


def load_json(file_path, default=None):
    """Загрузить JSON-файл с обработкой ошибок."""
    if not os.path.exists(file_path):
        return default
    try:
        with open(file_path, encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Corrupted JSON at %s: %s — resetting to default", file_path, e)
        return default
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Failed to load %s: %s", file_path, e)
        return default


def save_json(file_path, data):
    """Сохранить данные в JSON-файл атомарно."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    tmp_path = file_path + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, file_path)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Failed to save %s: %s", file_path, e)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def extract_html_from_json_response(text, log_callback=None):
    if not text:
        return text
    text = strip_thinking_tags(text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and 'html' in parsed:
            html = parsed['html']
            if log_callback:
                log_callback("  Извлечён HTML из JSON-объекта", 'info')
            return html
    except json.JSONDecodeError:
        pass
    return text
