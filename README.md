# NPA JSON Agent Processor

AI-agent-driven pipeline for applying NPA amendments from one JSON to another using structured prompts and deterministic output.

## Structure

```
AGENT_INSTRUCTION.md     - Framework instruction for the AI agent (in git)
instructions/            - Stage-specific instructions (in git)
examples/                - Characteristic examples for each stage (in git)
schema/                  - JSON structure documentation (in git)
prompts/                 - Agent prompts for processing stages (in git)
scripts/                 - Pipeline scripts and utilities (in git)
learning/                - Runtime learning data: run logs, mappings (NOT in git)
База/                     - Incomplete NPA database: JSON laws/resolutions (NOT in git)
work/                    - Working files (NOT in git)
  source/                - Source and target NPA JSONs
  answers/               - AI answers for each stage
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
3. Run the agent following `AGENT_INSTRUCTION.md`
4. Execute pipeline: `python -m npa_processor` or `python scripts/run_pipeline.py`

### Chain Pipeline

To apply multiple amendments sequentially:

1. Place target NPA and all amending NPAs in a folder
2. Prepare stage answers for each amendment (optional)
3. Run: `python scripts/chain_pipeline.py <input_folder>`
4. Intermediate results are saved in `work/chain_results/`

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
