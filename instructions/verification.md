# Verification Rules

## 1. STRUCTURAL VERIFICATION

### 1.1 Item IDs
- All `item_id` values must be unique across the entire document
- Format: `{npa_id}_{type}_{number}` (e.g., `16012_article_3_point_1`)
- No bare NPA numbers allowed in `modified_by_id`

### 1.2 Item Types
Allowed types:
- `preamble`, `chapter`, `section`, `article`, `part`, `point`
- `subpoint`, `appendix`, `nested_appendix`, `structured_table`, `paragraph`

### 1.3 Item Levels
- Root level starts at 1
- Each child level = parent level + 1
- No gaps allowed

### 1.4 Tree Integrity
- All `child_ref` in body must reference existing `item_id`
- All children in `item_children` must have corresponding `child_ref` in parent body
- No children inlined as HTML in parent body blocks

## 2. REVISION VERIFICATION

### 2.1 Active Revision
- Exactly ONE active revision per element (`valid_to` = null or empty)
- Active revision must have `valid_from`

### 2.2 Date Continuity
- `valid_to` of old revision = `valid_from` of new revision - 1 day
- All dates in `DD.MM.YYYY` format
- Dates must follow chronological order

### 2.3 Revision Fields
- `mod_type` must be one of: `new_redaction`, `add`, `delete`, `change`, `correction`, `renumber`, `editorial`
- `modified_by_id` must be present for non-original revisions

## 3. HIGHLIGHTS VERIFICATION

### 3.1 Presence
- Every revision with `mod_type = "change"` MUST have `highlights`

### 3.2 Format
```json
{
  "previous_edition": {
    "deletion": [{"text": "...", "positions": "M-N,M-N"}],
    "difference": [{"text": "...", "positions": "M-N"}]
  },
  "current_edition": {
    "addition": [{"text": "...", "positions": "M-N"}],
    "difference": [{"text": "...", "positions": "M-N"}]
  }
}
```

### 3.3 Content Rules
- ONLY changed fragments, not whole paragraphs
- Replacements always in pairs (previous + current difference)
- Additions only in `current_edition.addition`
- Deletions only in `previous_edition.deletion`

## 4. CHANGE COMPLETENESS

### 4.1 All Changes Applied
- Every change from stages 1-3 must be applied
- No changes skipped without documented reason

### 4.2 No Extra Changes
- No elements modified outside of specified changes
- No unauthorized structural modifications

## 5. ANTI-PATTERN CHECKS

### 5.1 Full HTML in Description
- `description` for `change`/`delete` must NOT contain full article HTML (>500 chars)
- If found → ERROR: replace with precise instruction

### 5.2 HTML in new_redaction/add Description
- `description` for `new_redaction`/`add` must NOT contain HTML tags
- Must contain only absolute paragraph numbers

### 5.3 Bare NPA Number
- `modified_by_id` must NOT be just the NPA number (e.g., `"37687"`)
- Must be full item_id (e.g., `"37687_article_1_point_1"`)

### 5.4 Collapsed Plural Delete
- Plural delete ("пункты 3 и 4") must be split into individual objects
- Single object at container level → ERROR

## 6. AUTO-FIX RULES

If verification finds errors, apply these fixes automatically:

| Error | Fix |
|-------|-----|
| Duplicate item_id | Add `_double_N` suffix |
| Missing child_ref | Add to parent body |
| Invalid date format | Correct to DD.MM.YYYY |
| Missing highlights | Generate from HTML diff |
| Inlined children | Extract to `item_children`, replace with `child_ref` |
| Bare modified_by_id | Replace with full item_id from change data |
| Collapsed plural delete | Split into individual objects |

## 7. REPORTING

All verification results must be reported:
- Passed checks: listed in summary
- Failed checks: detailed with element, expected, actual
- Auto-fixes applied: listed with before/after
- Unfixable errors: listed with recommended manual action
