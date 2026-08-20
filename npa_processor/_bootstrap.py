import os
import sys


def _bootstrap_project_root():
    current_dir = os.path.abspath(os.path.dirname(__file__))
    candidate = current_dir
    while True:
        has_pkg = os.path.isdir(os.path.join(candidate, 'npa_processor'))
        has_req = os.path.isfile(os.path.join(candidate, 'requirements.txt'))
        has_pyproject = os.path.isfile(os.path.join(candidate, 'pyproject.toml'))
        has_readme = os.path.isfile(os.path.join(candidate, 'README.md'))
        if has_pkg and (has_req or has_pyproject or has_readme):
            project_root = candidate
            break
        parent = os.path.dirname(candidate)
        if parent == candidate:
            project_root = current_dir
            break
        candidate = parent
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
