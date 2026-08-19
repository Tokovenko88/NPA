# Work Tools

## run_pipeline.py

Main pipeline script for processing NPA amendments. Executes stages 1-5 of the NPA JSON merging pipeline.

Usage:
```bash
python scripts/run_pipeline.py
python scripts/run_pipeline.py --source path/to/source.json --target path/to/target.json --dry-run --stage 3
```

### Flags
- `--source` — path to source NPA JSON
- `--target` — path to target NPA JSON
- `--result-dir` — custom result directory
- `--keep-previous` — preserve previous results
- `--strict` — abort on ambiguous resolution
- `--dry-run` — validate without writing output
- `--stage N` — run only up to stage N (1-5)

## chain_pipeline.py

Chain pipeline script for running multiple NPA processing tasks. Executes the pipeline in-process (no subprocess).

Usage:
```bash
python scripts/chain_pipeline.py <input_folder> [--target target_file.json] [--output work/chain_results] [--answers answers_base]
```
