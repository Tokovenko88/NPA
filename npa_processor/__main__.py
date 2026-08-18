# -*- coding: utf-8 -*-
import os
import sys


def bootstrap_project_root():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


bootstrap_project_root()


def run_pipeline():
    from scripts.run_pipeline import main as pipeline_main
    pipeline_main()


def main():
    run_pipeline()


if __name__ == "__main__":
    main()
