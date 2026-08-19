"""JSON-утилиты: загрузка, сохранение."""

import json
import os


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
