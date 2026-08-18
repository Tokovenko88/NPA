import os
import sys


def _bootstrap_project_root():
    current_dir = os.path.abspath(os.path.dirname(__file__))
    candidate = current_dir
    while True:
        if os.path.isdir(os.path.join(candidate, 'npa_processor')) and os.path.isfile(os.path.join(candidate, 'requirements.txt')):
            project_root = candidate
            break
        parent = os.path.dirname(candidate)
        if parent == candidate:
            project_root = current_dir
            break
        candidate = parent
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
