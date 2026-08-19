"""Централизованные пути и утилиты для проекта."""

import json
import os

from npa_processor._bootstrap import _bootstrap_project_root

_bootstrap_project_root()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

ANSWERS_DIR = os.path.join(PROJECT_ROOT, 'work', 'answers')
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'work', 'results')
SOURCE_DIR = os.path.join(PROJECT_ROOT, 'work', 'source')
CHAIN_RESULTS_DIR = os.path.join(PROJECT_ROOT, 'work', 'chain_results')
LEARNING_DIR = os.path.join(PROJECT_ROOT, 'learning')
REPORT_PATH = os.path.join(RESULTS_DIR, 'report.md')


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


def save_text(file_path, text):
    """Сохранить текстовые данные в файл."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)
