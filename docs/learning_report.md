# Self-Learning Mechanism: Design Report

## 1. Objective

The NPA JSON Agent must correctly apply real legal amendments to a target JSON NPA in 99% of cases on the first attempt. To achieve this, the learning mechanism preserves successful and failed iterations, but **failed iterations must never be promoted into trusted positive examples**.

## 2. Architecture Overview

### 2.1 Components

- **DocumentHistory** — snapshots and run-level metadata with case/attempt tracking.
- **LearningEngine** — mapping trust, outcome classification, failure pattern mining, recovery suggestions.
- **Verifier** — structural integrity checks that produce classification-ready errors.

### 2.2 Data Flow

1. **Apply** → agent resolves `structural_element → item_id` and applies change.
2. **Verify** → `StructureVerifier` validates the resulting document.
3. **Classify** → each change receives an outcome: `resolved`, `applied`, `verified_success`, `failed`, `verification_failed`, or custom.
4. **Record** → `DocumentHistory.finalize_run(...)` stores run outcomes and trust flags; `LearningEngine.record_mapping(...)` updates context-scoped mapping statistics.
5. **Consult** → subsequent runs query `get_reliable_mapping(...)` and `get_suggestions_for_element(...)` before applying changes.

## 3. Outcome Classification

| Outcome | Meaning | Trusted for Positive Learning | Diagnostic Only |
|---------|---------|------------------------------|-----------------|
| `resolved` | Element found in target | No | No |
| `applied` | Change applied locally | No | No |
| `verified_success` | Entire document passed verification | **Yes** | No |
| `failed` | Application error | No | **Yes** |
| `verification_failed` | Document failed structural verification | No | **Yes** |
| *unknown/custom* | Unrecognised outcome | No | **Yes** |

**Rule:** `success_count` for trusted mapping increases **only** on `verified_success`. `resolved` and `applied` are telemetry. `failed` and `verification_failed` decrease confidence and populate diagnostics.

## 4. Mapping Trust Model

### 4.1 Context Scoping

Mapping trust is computed **per context tuple**, not per `structural_element` string alone. Two identical strings (e.g. "статья 1") in different target NPAs map to different records.

Context key components:
- `target_npa_id`
- `source_npa_id` or `source_context`
- `structural_element`
- `change_type`
- `element_signature` (optional)

If no context is provided, backward compatibility is preserved: the legacy `success_count / fail_count` heuristic is used.

### 4.2 Confidence Formula

```
confidence = verified_success_count /
             (verified_success_count
              + verification_fail_count
              + apply_fail_count
              + 2)
```

Additional fields stored per mapping:
- `last_verified_success`
- `last_failure`
- `failure_categories`
- `case_ids` — deduplicated list of case identifiers
- `contested` — `True` if at least one `verified_success` and at least one failure exist

### 4.3 Case-Level Deduplication

Multiple failed attempts within the **same `case_id`** are stored as a single diagnostic event. This prevents one noisy case from destroying global mapping confidence. `case_ids` is a deduplicated list.

## 5. DocumentHistory Enhancements

### 5.1 Run Metadata

`DocumentHistory` now accepts optional `case_id`, `attempt_id`, and `iteration_number` in `__init__`. These are persisted in `_index.json`.

### 5.2 Finalization

`finalize_run(outcomes, metadata=None)`:
- Accepts a list of change outcomes.
- Computes `trusted_for_positive_learning` (True only if all outcomes are `verified_success` or `applied`/`resolved` and there are no failures or unknowns).
- Computes `diagnostic_learning_only` (True if any outcome is `failed`, `verification_failed`, or unknown).
- Returns `final_metadata` dict with counters and flags.

## 6. Risks, Promotion Rules, and Metrics

### 6.1 Current Risks

| Risk | Mitigation |
|------|-----------|
| Mapping without target/source context | Context is now a first-class key component. |
| Local `success` inflating confidence | `resolved`/`applied` no longer increase trusted `verified_success_count`. |
| Repeated failures from one case distorting statistics | `case_ids` deduplication; failures are diagnostic-only. |
| No lifecycle for promotion | Explicit promotion rules below. |

### 6.2 Promotion Rules

| Source | Target | Condition |
|--------|--------|-----------|
| `failed` attempt | Anti-pattern | Error category repeats ≥ 3 times across distinct cases. |
| `failed` attempt | Regression test | Failure is reproducible and structurally deterministic. |
| `verified_success` | Characteristic example | First verified success for a (target, source, change_type) tuple. |
| Recovery success | Recovery strategy | Same recovery suggestion fixes ≥ 2 distinct cases. |
| `contested` mapping | Manual review / stricter resolver | Confidence < 0.33 and contested flag is set. |

### 6.3 Quality Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| First-pass success rate | ≥ 99% | Share of runs where all changes reach `verified_success` on first attempt. |
| Verified success rate by change type | ≥ 95% per type | Share of `verified_success` per `change_type` (`new_redaction`, `add`, `delete`, `change`). |
| Contested mapping count | ≤ 5% of total mappings | Mappings with both successes and failures. |
| Repeated failure signatures | ≤ 10% of runs | Same `(structural_element, error_category)` pair failing ≥ 3 times. |
| Recovery success rate | ≥ 70% | `success_count > fail_count` among recorded recovery attempts. |
| False-positive mapping reuse count | 0 | A mapping from one target NPA incorrectly reused for a different target NPA. |

## 7. Testing

The new test suite (`tests/test_learning_history.py`) covers:

- `test_history_index_records_case_attempt_metadata` — `case_id`, `attempt_id`, `iteration_number` are persisted in `_index.json`.
- `test_unknown_outcome_is_diagnostic_only` — custom outcomes set `diagnostic_learning_only=True`.
- `test_mapping_context_prevents_cross_npa_reuse` — identical `structural_element` with different `target_npa_id` produces separate mapping keys.
- `test_resolved_mapping_does_not_increase_verified_confidence` — `resolved` outcome increments telemetry but not `verified_success_count`.
- `test_repeated_failures_in_one_case_are_deduplicated_for_global_confidence` — 10 failures from one `case_id` produce a single `case_id` entry and set `contested=True`.

## 8. Rebuild Planning

`rebuild_order(...)` now includes ancestors of the effective set in deterministic child-first order. `build_rebuild_plan(...)` retains its original contract: it returns only the effective requested IDs (ancestors are available via `parent_map` for runtime coordination).

## 9. Future Work

- Implement the full promotion lifecycle: anti-pattern → regression test → characteristic example.
- Add `recovery_strategy` promotion from recovery log.
- Integrate contested mapping alerts into the agent prompt supplement.
- Automate metric collection from `learning_log.json` and `verification_log.json`.
