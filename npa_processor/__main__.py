from npa_processor._bootstrap import _bootstrap_project_root

_bootstrap_project_root()


def run_pipeline():
    from scripts.run_pipeline import main as pipeline_main
    pipeline_main()


def main():
    run_pipeline()


if __name__ == "__main__":
    main()
