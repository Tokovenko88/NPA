# Stage 5: Apply Changes to JSON

## 1. TASK

Apply all collected changes to the target NPA JSON, producing a legally valid amended document.

## 2. INPUT

- `target_npa.json` — the target NPA JSON structure
- Stage 1-4 outputs — all changes and processed HTML
- `valid_from` — general effective date from source NPA

## 3. OUTPUT

Modified `target_npa.json` with all changes applied, plus verification report.

## 4. CRITICAL RULES

### 4.1 modified_by_id FORMAT
`modified_by_id` = FULL `item_id` of the source element in format `{npa_id}_{type}_{number}`

Examples:
- `"33699_article_1_point_2"`
- `"46989_article_1_point_1_subpoint_а"`

**FORBIDDEN:** Using only the NPA number (e.g., `"33699"`). This is a critical error.

### 4.2 NEW REDACTION BODY SOURCE

For `new_redaction`, the parent revision body MUST be taken exclusively from the canonical parser / Stage 4 output.

- The previous revision body MUST NOT be used as a source of structure for the new revision.
- `child_ref` entries from the previous revision MUST NOT be automatically copied into the new revision body.
- Existing child elements may remain in the global document structure because history must be preserved, but their `child_ref` MUST NOT appear in the new parent revision unless the canonical new body explicitly contains that `child_ref`.
- Child synchronization is a separate operation performed AFTER the canonical parent body has been established.

### 4.3 TREE STRUCTURE PRESERVATION

When applying `new_redaction` to an element with children:
- Children MUST remain in `item_children`
- Parent `body` MUST contain ONLY:
  - `paragraph` blocks with direct content from canonical parser output
  - `child_ref` blocks ONLY if they are explicitly present in the canonical parser output
- NEVER inline children HTML into parent body
- NEVER inherit child_ref from previous revision merely because the child existed previously

### 4.3 REVISION MANAGEMENT
- Close active revision: `valid_to` = (new_date - 1 day)
- Create new revision: `valid_from` = new_date
- Only ONE active revision per element (`valid_to` = null)

### 4.4 HIGHLIGHTS REQUIREMENT
For `type = "change"` ONLY, the `highlights` field MUST be populated. Missing highlights is a critical error.
For all other types (`new_redaction`, `add`, `delete`, `special_valid_from`), `highlights` MUST NOT be populated.

Highlights format:
```json
{
  "previous_edition": {
    "deletion": [["removed_text", "M-N"]],
    "addition": [],
    "difference": [["old_text", "M-N"]]
  },
  "current_edition": {
    "deletion": [],
    "addition": [["added_text", "M-N"]],
    "difference": [["new_text", "M-N"]]
  }
}
```

### 4.5 DATE FORMAT
All dates in `DD.MM.YYYY` format.

## 5. CHANGE TYPE APPLICATION

### 5.1 DELETE
1. Find element by `structural_element_for_delete`
2. Set `valid_to` of active revision = (date - 1 day)
3. Add `not_valid` = `modified_by_id` to old revision
4. Create new revision with `mod_type = "delete"`, empty `body`

### 5.2 SPECIAL_VALID_FROM
1. Find element in source or target NPA
2. Set `valid_to` of active revision = (date - 1 day)
3. Create new revision with `mod_type = "new_redaction"`, `valid_from` = date

### 5.3 RETROACTIVE_NOTE
1. Find element in target NPA
2. Add to `item_notes`:
```json
{
  "text": "Действие положений [structural_element] распространяется на правоотношения, возникшие с [date]",
  "valid_from": "[date]",
  "valid_to": ""
}
```

### 5.4 NEW_REDACTION
1. Find element in target NPA
2. Set `valid_to` of active revision = (date - 1 day)
3. Create new revision:
   - `mod_type = "new_redaction"`
   - `modified_by_id` = full item_id from source
   - `body` = new content blocks
   - DO NOT include `highlights`

### 5.5 ADD
1. Find parent element
2. Create new child element with `mod_type = "add"`
3. Add `child_ref` to parent body
4. Update parent revision

### 5.6 CHANGE
1. Find element in target NPA
2. Apply HTML changes from stage 4
3. Create new revision:
   - `mod_type = "change"`
   - `modified_by_id` = full item_id from source
   - `body` = modified HTML blocks
   - `highlights` = MANDATORY

## 6. VERIFICATION

After applying all changes:
1. Run structural verification
2. Run change completeness check
3. Fix any errors automatically if possible
4. Document unfixable errors in report

## 7. EXAMPLES

See `examples/stage_5/characteristic_examples.json` for reference patterns.

## 8. ANTI-PATTERNS

See `examples/common/anti_patterns.json` for known failure modes.
