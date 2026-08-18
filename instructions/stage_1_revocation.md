# Stage 1: Revocation Analysis

## 1. TASK

Analyze the source NPA HTML text to find all indications that specific structural elements of the target NPA have lost force (are revoked).

## 2. INPUT

- `source_npa.json` — full HTML text of the amending law
- Target NPA number: `{law_number}`

## 3. OUTPUT FORMAT

Return a JSON array of objects, or `null` if nothing found:

```json
[
  {
    "structural_element": "статья 1",
    "structural_element_for_delete": "law",
    "valid_from": null
  }
]
```

Fields:
- `structural_element` — full path to the element IN THE SOURCE NPA where the revocation indication is located. Use ` -> ` as separator. Nominative case only.
- `structural_element_for_delete` — what loses force in the TARGET NPA. Use `"law"` for the entire law, or full hierarchical path for partial revocation.
- `valid_from` — date when force is lost (DD.MM.YYYY), or `null` if not specified.

## 4. CRITICAL RULES

### 4.1 DIRECT OBJECT ONLY
Revocation must apply DIRECTLY to the target NPA. If the target NPA is mentioned ONLY inside the title of another revoked law (e.g., "Law on amendments to Law X..."), this does NOT mean the target NPA loses force. IGNORE such mentions.

### 4.2 SPLIT RANGES AND LISTS
If revocation applies to a range ("articles 3-5") or list ("points 3 and 4"), create ONE object per element:
- "articles 3-5" → 3 objects: article 3, article 4, article 5
- "points 3 and 4" → 2 objects: point 3, point 4

### 4.3 DATE FORMAT
Always use `DD.MM.YYYY`. If the date is given in words (e.g., "1 January 2024"), convert it.

### 4.4 STRUCTURAL ELEMENT FORMAT
- Use only nominative case
- Use Arabic numerals for numbered elements
- Preserve Roman numerals and superscript signs exactly as in source
- Order: highest level to lowest level
- Correct: `"статья 4 -> часть 2 -> пункт 1"`
- Incorrect: `"часть 2 статьи 4 пункт 1"` (wrong case and order)

## 5. VERIFICATION

Before outputting:
- [ ] Each object has all required fields
- [ ] `structural_element` follows hierarchy rules
- [ ] Plural deletions are split into individual objects
- [ ] No indirect mentions treated as direct revocations

## 6. EXAMPLES

See `examples/stage_1/characteristic_examples.json` for reference patterns.

## 7. ANTI-PATTERNS

See `examples/common/anti_patterns.json` for known failure modes.
