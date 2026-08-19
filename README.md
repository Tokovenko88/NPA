# NPA JSON Agent Processor

Agent-driven pipeline for applying NPA amendments from one JSON to another using structured prompts and deterministic output.

## Architecture

The pipeline has a strict agent ↔ script contract:

- **Stages 1–4:** The agent analyzes source/target NPA using prompts, instructions, examples, and learning data. It writes JSON answer files under `work/answers/`.
- **Stage 5:** Scripts read the agent-produced answer files and apply them deterministically to the target JSON. No generative step occurs inside scripts and no external AI/LLM APIs are called.

## Structure

```
AGENT_INSTRUCTION.md     - Framework instruction for the agent (in git)
instructions/            - Stage-specific instructions (in git)
examples/                - Characteristic examples for each stage (in git)
schema/                  - JSON structure documentation (in git)
prompts/                 - Agent prompts for processing stages (in git)
scripts/                 - Pipeline scripts and utilities (in git)
learning/                - Runtime learning data: run logs, mappings (NOT in git)
База/                     - Incomplete NPA database: JSON laws/resolutions (NOT in git)
work/                    - Working files (NOT in git)
  source/                - Source and target NPA JSONs
  answers/               - Agent stage answers
  results/               - Final NPA after applying changes
  chain_results/         - Intermediate results for chain pipeline
npa_processor/           - Core processing engine (in git)
```

## Git Policy

- **Stored in git:** instructions, schema docs, prompts, examples, scripts, core engine, README
- **Not stored in git:** working files, learning data, База, reports, temporary files

## Usage

1. Place source NPA in `work/source/source_npa.json`
2. Place target NPA in `work/source/target_npa.json`
3. Run the agent following `AGENT_INSTRUCTION.md` to produce answer files in `work/answers/`
4. Execute pipeline: `python -m npa_processor` or `python scripts/run_pipeline.py`

### Answer File Names

The agent must produce these files under `work/answers/`:
- Stage 1: `prompt_1_answer.json`
- Stage 2: `prompt_2_answer.json`
- Stage 3: `prompt_3_answer.json` (or per-article variants)
- Stage 4: `prompt_4_answer_{key}.json` (e.g. `{item_id}_content`, `head`, `prefix_{id}`)

### CLI Flags

```bash
python scripts/run_pipeline.py --source path/to/source.json --target path/to/target.json --dry-run --stage 3
```

- `--source` — path to source NPA JSON (default: `work/source/source_npa.json`)
- `--target` — path to target NPA JSON (default: `work/source/target_npa.json`)
- `--dry-run` — validate and plan changes without writing output
- `--stage N` — executes stages 1..N inclusively; stages > N are skipped (1: revocation/dates, 2: dates, 3: load changes, 4: learning supplement for text, 5: apply + rebuild)
- `--result-dir` — custom result directory (default: `work/results`)
- `--keep-previous` — do not delete previous results
- `--strict` — abort on ambiguous element resolution

### Chain Pipeline

To apply multiple amendments sequentially:

1. Place target NPA and all amending NPAs in a folder
2. Prepare stage answers for each amendment (optional)
3. Run: `python scripts/chain_pipeline.py <input_folder>`
4. Intermediate results are saved in `work/chain_results/`

### JSON Schema

Formal JSON schemas are available in `schema/`:
- `npa_schema.json` — structure of NPA documents
- `stage3_answer_schema.json` — structure of stage 3 changes extraction answers

## Self-Learning

The agent records each pipeline run into `learning/`:
- `learning_log.json` — run outcomes, applied/failed changes, manual corrections
- `element_mappings.json` — reliable element mappings between structural paths and item_ids
- `prompt_feedback.json` — prompt effectiveness by stage

The agent consults these files before applying changes to reuse proven mappings and avoid previously failed patterns.

## Agent Capabilities

The agent can:
- Analyze revocation, dates, and changes from source NPA
- Apply changes deterministically to target NPA JSON
- Verify structural integrity and referential validity
- Learn from failures and improve its own code, instructions, and examples
- Report issues found in База without modifying it

## Development notes

- Dead code cleanup and unification of helpers (`sup_digits_to_unicode`, `log`, `close_revision_date`, tree helpers).
- Bootstrap is centralized in `npa_processor/_bootstrap.py`.
- Logging helper: `npa_processor.logging_utils.log`.
