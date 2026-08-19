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
python scripts/chain_pipeline.py <input_folder> [--target target_file.json] [--output work/chain_results] [--answers answers_base] [--stop-on-error]
```

### Flags
- `input_folder` — folder containing target and amendment JSON files
- `--target` — explicit target filename in input folder (optional)
- `--output` — output directory for chain results (default: `work/chain_results`)
- `--answers` — base folder with stage answers per amendment (optional)
- `--stop-on-error` — stop chain on first step failure (default: continue to next amendment)

### Behavior
- The chain pipeline applies amendments sequentially in chronological order.
- On step failure, it logs the error and continues to the next amendment by default.
- With `--stop-on-error`, the chain halts on the first failure.
- Intermediate results are saved in `work/chain_results/`.
