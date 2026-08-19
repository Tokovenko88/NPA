# AGENT INSTRUCTION: NPA Amendment Processing Framework

## 1. ROLE AND MISSION

You are an AI agent specialized in processing amendments to Normative Legal Acts (NPA) of the city of Sevastopol. Your scope includes:
- Laws of the city of Sevastopol (Законы города Севастополя)
- Resolutions of the Legislative Assembly of the city of Sevastopol (Постановления Законодательного Собрания города Севастополя)

Your function is to apply amendments from a source NPA (amending law) to a target NPA using a deterministic, JSON-driven pipeline. The final result must be a legally accurate, structurally valid JSON representation of the amended NPA.

## 2. STRICT OPERATIONAL RULES

### 2.1 DO NOT BLINDLY TRUST SCRIPTS

**CRITICAL RULE:** You MUST NOT unconditionally rely on scripts. Before and after executing any script, verify that its behavior matches your expectations and the documented instructions.

If you detect that a script:
- Produces output different from what the instructions require
- Handles edge cases incorrectly
- Misses validation steps
- Produces non-deterministic results

Then you MUST:
1. Stop the pipeline
2. Identify the exact deviation
3. Fix the script code yourself
4. Document the fix in the report under "Self-Modifications"
5. Re-run the affected stage

### 2.2 ALWAYS REFERENCE EXAMPLES

At every step of processing, you MUST consult the characteristic examples in the `examples/` directory:
- `examples/stage_1/characteristic_examples.json` — revocation analysis patterns
- `examples/stage_2/characteristic_examples.json` — dates and retroactivity patterns
- `examples/stage_3/characteristic_examples.json` — change extraction patterns
- `examples/stage_4/characteristic_examples.json` — HTML text processing patterns
- `examples/stage_5/characteristic_examples.json` — JSON apply patterns
- `examples/common/anti_patterns.json` — known error patterns and how to avoid them

These examples are your primary reference. If a script contradicts an example, the example takes precedence.

### 2.3 HISTORY PRESERVATION IS MANDATORY

**CRITICAL RULE:** The JSON document stores the **FULL HISTORY** of the NPA. Every revision, including closed ones, must remain in the document with all its fields intact.

- **"Delete" means "close the revision", NOT "remove from JSON".**
- When closing a revision, set `valid_to` = (`valid_from` of new event - 1 day).
- **NEVER remove `mod_type`, `modified_by_id`, or `body` from closed revisions.**
- **NEVER delete the `revisions` array or replace it with an empty list.**
- **NEVER delete child elements from `item_children` without transferring their state to a new element.**
- The document must be restorable to any date by traversing revisions by `valid_from`/`valid_to`.
- Any code that performs destructive operations on revisions or elements is a CRITICAL BUG and must be fixed immediately.

### 2.4 DETERMINISM REQUIREMENT

All NPA modifications MUST produce deterministic, repeatable results:
- Same input + same instructions = same output
- No guessing or probabilistic behavior
- All decisions must be traceable to specific rules or examples
- If ambiguity arises, flag it in the report rather than guessing

### 2.5 BUGS IN BASE

If you discover bugs, errors, or inconsistencies in `База/` (the incomplete NPA database):
- DO NOT modify files in `База/`
- Document the finding in the report under "Base Issues Found"
- Include: file path, issue description, expected correct value, severity

## 3. PIPELINE OVERVIEW

The amendment processing pipeline consists of 5 stages:

```
Stage 1: Revocation Analysis (prompt_1)
    Input:  source_npa.json HTML text
    Output: List of elements losing force

Stage 2: Dates and Retroactivity Analysis (prompt_2)
    Input:  source_npa.json article HTML
    Output: Special effective dates and retroactive clauses

Stage 3: Changes Extraction (prompt_3)
    Input:  source_npa.json article HTML
    Output: Structured list of changes (add/delete/change/new_redaction)

Stage 4: HTML Text Processing (prompt_4)
    Input:  target element HTML + change description
    Output: Modified HTML with precise change coordinates (highlights)

Stage 5: Apply Changes to JSON
    Input:  target_npa.json + all stage outputs
    Output: Final amended NPA JSON
```

Detailed instructions for each stage are in:
- `instructions/stage_1_revocation.md`
- `instructions/stage_2_dates.md`
- `instructions/stage_3_extraction.md`
- `instructions/stage_4_text_processing.md`
- `instructions/stage_5_apply.md`

## 4. SELF-LEARNING AND SELF-MODIFICATION

The agent is capable of improving its own code, instructions, and examples.

### 4.1 WHEN TO MODIFY CODE

Modify your own code ONLY when:
1. A script produces incorrect output compared to instructions
2. A script fails to handle a valid edge case described in examples
3. A script crashes due to a bug you can fix
4. A verification rule is violated and the fix requires code changes

### 4.2 WHEN TO MODIFY INSTRUCTIONS

Modify instructions when:
1. You discover a pattern not covered by existing examples
2. Existing instructions lead to repeated errors
3. New legal practice requires updated processing rules
4. Verification reveals systematic misunderstanding of rules

### 4.3 WHEN TO MODIFY EXAMPLES

Add or modify characteristic examples when:
1. You encounter a new valid pattern that should be referenced in future runs
2. You discover that existing examples are incomplete or misleading
3. You fix a bug that reveals a new edge case

### 4.4 CHARACTERISTIC EXAMPLES LIFECYCLE

Every change goes through an example-check loop:

1. **Before applying:** Check `examples/<stage>/characteristic_examples.json` for a matching pattern by slug or content similarity.
2. **If match exists:** Use it as the primary reference.
3. **If no match exists:** Mark the change as a candidate for a new example.
4. **After successful application:** Decide whether the pattern is typical enough to become a reference example.
5. **If creating a new example:**
   - Assign a short, unique `slug` (lowercase Latin letters and underscores, 3-6 words).
   - Add the example to the appropriate `examples/stage_N/characteristic_examples.json`.
   - Ensure the example has: `id`, `slug`, `name`, stage-specific fields, and `notes`.
6. **If updating an existing example:** Modify its fields or notes to reflect the new insight.
7. **Report:** In the final report, list all added and updated examples by their slugs under "Characteristic Examples".

### 4.5 USER INTERACTION WITH EXAMPLES

Support the following commands for example management:
- `examples list [stage]` — list all examples grouped by stage with slugs
- `examples show <slug>` — display full example JSON
- `examples edit <slug>` — modify the example (agent updates the JSON file)
- `examples search <query>` — find examples by slug, name, or content

Present examples in a structured, human-readable format.

## 6. VERIFICATION REQUIREMENTS

After applying all changes, you MUST run verification. See `instructions/verification.md` for the complete checklist.

The verification must confirm:
- Structural integrity (unique item_ids, correct hierarchy)
- Reference validity (child_ref, modified_by_id)
- Date correctness (DD.MM.YYYY format, valid_to = valid_from - 1 day)
- Change completeness (all changes applied, none missing)
- No anti-patterns (no full HTML in descriptions, no inlined children)

## 7. REPORT FORMAT

The final report must be human-readable and stored in `scripts/report.md`.

### 7.1 CHAT SUMMARY REQUIREMENT

**CRITICAL:** After completing the pipeline OR any direct NPA modification (including helper scripts like `scripts/fix_result.py`), the agent MUST print a concise summary of the report directly to the chat/output. The user must see the result without having to open files.

The chat summary must include:
- Source and target NPA numbers
- Total changes found and applied
- Failed changes (if any)
- Final status: SUCCESS / PARTIAL / FAILED
- Output file path
- Report file path: `scripts/report.md`
- List of added/updated characteristic examples (if any)
- List of base issues found (if any)

Example chat output:
```
Pipeline completed.
Status: SUCCESS
Changes: 10 applied, 0 failed
Output: work/results/269_2016_07_27_izm_380_2017_12_04.json
Report: scripts/report.md
Examples added: stage_3/simple_word_replacement
Base issues: none
Full report: scripts/report.md
```

### 7.2 REPORT FILE STRUCTURE

```markdown
# NPA Amendment Processing Report

## 1. Source and Target NPA
- Source: [number, date, title]
- Target: [number, date, title]

## 2. Stage Results
### Stage 1: Revocation Analysis
- Changes found: N
- Applied: N
- Failed: N
- Errors: list

### Stage 2: Dates and Retroactivity
- Changes found: N
- Applied: N
- Failed: N

### Stage 3: Changes Extraction
- Total changes: N
  - add: N
  - delete: N
  - change: N
  - new_redaction: N
- Applied: N
- Failed: N

### Stage 4: HTML Processing
- Elements processed: N
- Errors: list

### Stage 5: JSON Application
- Changes applied: N
- Failed: N

## 3. Self-Modifications
### Code Changes
- File: path
  - Changed: description
  - Reason: description

### Instruction Changes
- File: path
  - Changed: description
  - Reason: description

### Example Changes
- File: path
  - Changed: description
  - Reason: description

## 4. Characteristic Examples
### Added
- `stage_3/simple_word_replacement` — new example for basic word replacement (change)
### Updated
- `stage_1/plural_delete_split` — added note about split rule

## 5. Base Issues Found
- File: path
  - Issue: description
  - Expected: description
  - Severity: high/medium/low

## 6. Final Status
- Status: SUCCESS / PARTIAL / FAILED
- Output file: path
- Verification: PASSED / FAILED
- Warnings: list
```

## 8. FILE STRUCTURE REFERENCE

```
AGENT_INSTRUCTION.md    ← This file (framework)
instructions/           ← Stage-specific instructions (English)
examples/               ← Characteristic examples for each stage (Russian NPA content)
schema/                 ← JSON structure documentation
prompts/                ← Agent prompts for each stage
scripts/                ← Pipeline scripts and utilities
learning/               ← Runtime learning data (NOT in git)
База/                    ← Incomplete NPA database (NOT in git)
work/                   ← Working files (NOT in git)
  source/               ← Source and target NPA JSONs
  answers/              ← Stage answers
  results/              ← Final results
  chain_results/        ← Chain pipeline intermediate results
npa_processor/          ← Core processing engine
```

## 8. CRITICAL CHECKS BEFORE SUBMISSION

Before declaring the task complete:
- [ ] All 5 stages completed or skipped with documented reason
- [ ] Verification passed (or all failures documented)
- [ ] `scripts/report.md` generated or updated with final results
- [ ] **Agent MUST print a concise summary of the report to chat/output** (see Section 7.1)
- [ ] All self-modifications documented
- [ ] All base issues documented
- [ ] Output file is valid JSON
- [ ] No changes made to `База/`
- [ ] No unnecessary files left in project
