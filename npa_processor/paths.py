"""Централизованные пути и утилиты для проекта."""

import os

from npa_processor._bootstrap import _bootstrap_project_root
from npa_processor.processing.json_utils import load_json, save_json

_bootstrap_project_root()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

ANSWERS_DIR = os.path.join(PROJECT_ROOT, 'work', 'answers')
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'work', 'results')
SOURCE_DIR = os.path.join(PROJECT_ROOT, 'work', 'source')
CHAIN_RESULTS_DIR = os.path.join(PROJECT_ROOT, 'work', 'chain_results')
LEARNING_DIR = os.path.join(PROJECT_ROOT, 'learning')
REPORT_PATH = os.path.join(RESULTS_DIR, 'report.md')


def save_text(file_path, text):
    """Сохранить текстовые данные в файл."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)
