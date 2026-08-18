# Self-Learning and Self-Modification

## 1. PURPOSE

This document defines the rules for the agent's self-learning capabilities and self-modification of its own code, instructions, and examples.

## 2. WHEN TO RECORD LEARNING DATA

Record learning data after EVERY pipeline run, regardless of success or failure.

### 2.1 SUCCESSFUL RUN
- Record the mapping between structural_element → resolved item_id
- Record effective prompts and parameters
- Update success counters in learning data

### 2.2 FAILED RUN
- Record the failure category (element_not_found, modified_by_id_bare, description_contains_html, etc.)
- Record the structural_element that failed
- Record error details and context
- Update failure counters

### 2.3 RECOVERY
If a failed change is successfully recovered:
- Record what recovery strategy worked
- Update reliable mappings if applicable

## 3. WHEN TO MODIFY CODE

Modify Python code in `npa_processor/` or `scripts/` ONLY when:

1. **Script produces wrong output:** The script output contradicts instructions or examples
2. **Script crashes on valid input:** A valid edge case causes an unhandled exception
3. **Verification fails due to code bug:** Structural or referential integrity failures that trace to code logic
4. **Performance issues:** Timeouts or resource exhaustion with fixable causes

**DO NOT modify code for:**
- Data errors (fix data or report the issue)
- Prompt errors (fix prompts or examples)
- One-off edge cases that can be handled by instructions

## 4. WHEN TO MODIFY INSTRUCTIONS

Modify instruction files in `instructions/` when:

1. **New pattern discovered:** A valid NPA pattern is not covered by existing examples
2. **Systematic errors:** The same type of error occurs repeatedly
3. **Legal practice update:** New amendment patterns emerge from recent laws
4. **Clarification needed:** Existing instructions are ambiguous or contradictory

## 5. WHEN TO MODIFY EXAMPLES

Modify files in `examples/` when:

1. **Missing example:** A new valid pattern needs a reference example
2. **Incorrect example:** An existing example contains an error
3. **Incomplete example:** An example doesn't cover edge cases that frequently cause errors

## 5.1 EXAMPLE LIFECYCLE AND AUTO-CREATION

### 5.1.1 CHECK BEFORE APPLY
Before applying a change, check whether a **characteristic example** for this pattern already exists in `examples/<stage>/characteristic_examples.json`.

- Compare the current change against existing examples by `type`, `structural_element` shape, and instruction pattern.
- If a matching example exists → reuse it as the reference.
- If no matching example exists → mark this change as **candidate for new example**.

### 5.1.2 CREATE AFTER SUCCESS
After the change is **successfully applied and verified**:

1. Determine whether this is a **typical/common** pattern or a **unique** one.
   - **Typical:** the pattern repeats across multiple amendments (e.g., standard word replacement, standard add/delete).
   - **Unique:** the pattern differs significantly from all existing examples (new legal wording, new table structure, new revocation form).
2. If **unique** → create a new characteristic example.
3. If **typical** but **no example exists** → create one, because it fills a gap in the reference base.
4. If **typical** and an example exists → do NOT duplicate; optionally refine the existing example if the new case adds useful detail.

### 5.1.3 SLUG ASSIGNMENT
Every characteristic example must have a short, unique `slug` for user-friendly referencing.

Rules for slugs:
- Lowercase Latin letters and underscores only
- Short (3-6 words max)
- Descriptive of the pattern
- Unique within the stage file

Examples of good slugs:
- `full_law_revocation`
- `plural_delete_split`
- `simple_word_replacement`
- `new_redaction_preserve_children`

### 5.1.4 EXAMPLE STRUCTURE
Each example object must contain:
- `id` — internal sequential ID (e.g., `s3_ex_10`)
- `slug` — short reference name
- `name` — human-readable title in Russian
- Stage-specific fields (`source_text`, `expected_output`, `change`, etc.)
- `notes` — explanation of why this pattern matters

### 5.1.5 USER INTERACTION
The agent must support the following user commands related to examples:

| Command | Behavior |
|---------|----------|
| `examples list [stage]` | Print categorized list of all examples with their slugs and names |
| `examples show <slug>` | Print full JSON of the example with this slug |
| `examples edit <slug>` | Open the example for editing (the agent modifies the JSON file) |
| `examples search <query>` | Find examples matching the query by slug, name, or content |

When the user requests examples, present them in a structured, human-readable format grouped by stage.

### 5.1.6 REPORTING
In the final report, the agent MUST include a section:

```markdown
## Characteristic Examples
### Added
- `stage_3/simple_word_replacement` — new example for basic word replacement
### Updated
- `stage_1/plural_delete_split` — added note about split rule
```

Only report examples that were **added or updated** during the current run. Do not list unchanged examples.

## 7. SELF-MODIFICATION PROTOCOL

When you modify any of your own artifacts:

```markdown
### [Timestamp] Self-Modification Record

**Type:** Code / Instruction / Example
**File:** `path/to/file`
**Section:** specific section or line range

**What was changed:**
[Brief description of the change]

**Why it was changed:**
[Trigger: bug, missing pattern, systematic error, etc.]

**Impact:**
[What behavior changed, what was fixed]
```

### 7.1 CODE MODIFICATION RULES
- Make minimal changes
- Preserve existing APIs and interfaces
- Add comments explaining the fix (in English)
- Test the modified code path if possible

### 7.2 INSTRUCTION MODIFICATION RULES
- Preserve existing structure and formatting
- Add new sections rather than rewriting existing ones
- Update cross-references if structure changes
- Keep language English (AI-understandable)

### 7.3 EXAMPLE MODIFICATION RULES
- Add new example objects rather than modifying existing ones (when possible)
- If modifying existing examples, document the reason
- Ensure examples remain valid JSON
- Keep Russian content accurate to actual NPA text

## 8. VERIFICATION AFTER SELF-MODIFICATION

After any self-modification:
1. Re-run the affected pipeline stage
2. Verify the fix resolves the issue
3. Check that no regressions were introduced
4. Update learning data with the outcome

## 9. PROHIBITED ACTIONS

The agent MUST NOT:
- Delete or modify files in `База/`
- Commit changes without explicit user request
- Modify files outside the project scope
- Share or log secrets, keys, or credentials
- Make speculative changes without documented trigger

## 10. LEARNING DATA STRUCTURE

Learning data is stored in `learning/` (NOT in git):

```
learning/
├── learning_log.json         — Run outcomes
├── element_mappings.json     — Reliable structural_element → item_id mappings
├── prompt_feedback.json      — Prompt effectiveness by stage
├── verification_log.json     — Detailed verification results
├── change_outcomes.json      — Per-change success/failure
├── recovery_log.json         — Successful recovery strategies
├── run_log.json              — Run metadata
├── error_examples.json       — Catalog of error patterns
├── bug_fixes.json            — Applied bug fixes and their effects
└── seed_examples.json        — Training examples for prompts
```

## 11. FEEDBACK LOOP

```
Pipeline Run
    ↓
Verification
    ↓
Failure Analysis
    ↓
┌───────────────┬───────────────┬───────────────┐
│  Code Bug?    │ Instruction   │  Missing      │
│               │  Gap?         │  Example?     │
└───────┬───────┴───────┬───────┴───────┬───────┘
        │               │               │
        ↓               ↓               ↓
  Fix Code        Update           Add Example
        │         Instructions           │
        │               │               │
        └───────────────┴───────────────┘
                        │
                        ↓
              Re-run and Verify
                        │
                        ↓
              Update Learning Data
```
