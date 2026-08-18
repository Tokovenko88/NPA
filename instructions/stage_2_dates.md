# Stage 2: Dates and Retroactivity Analysis

## 1. TASK

Analyze each article of the source NPA to find:
1. Special effective dates (exceptions from the general effective date)
2. Retroactive clauses (provisions whose effect extends to legal relations arising earlier)

## 2. INPUT

- `source_npa.json` — HTML text of a single article from the amending law
- `date_pub` — publication date of the source NPA
- `law_number` — number of the target NPA
- `article_number` — number of the current article being analyzed

## 3. OUTPUT FORMAT

Return a JSON array of objects, or `null` if nothing found:

### Special effective date:
```json
{
  "applies_to": "amending_law",
  "action_type": "special_valid_from",
  "structural_element": "статья 3 -> пункт 2 -> подпункт б -> абзац 3",
  "date": "01.01.2024"
}
```

### Retroactive clause:
```json
{
  "applies_to": "target_law",
  "action_type": "retroactive_note",
  "structural_element": "статья 3",
  "note_text": "Действие положений статьи 3 распространяется на правоотношения, возникшие с 7 июля 2023 года",
  "note_valid_from": null
}
```

Fields:
- `applies_to` — `"amending_law"` or `"target_law"`
- `action_type` — `"special_valid_from"` or `"retroactive_note"`
- `structural_element` — full path to the affected element
- `date` — special effective date (DD.MM.YYYY)
- `note_text` — full retroactive clause text
- `note_valid_from` — date for retroactive clause, or `null`

## 4. CRITICAL RULES

### 4.1 DISTINGUISH LAWS
- "Present law" (настоящий Закон) refers to the SOURCE NPA
- Target NPA is identified by `{law_number}` and title

### 4.2 SPECIAL DATES
Look for phrases like:
- "вступает в силу с [date], за исключением [element]"
- "[element] вступает в силу с [date]"

### 4.3 RETROACTIVE CLAUSES
Look for phrases like:
- "Действие положений [elements] Закона № {law_number} ... распространяется на правоотношения..."

### 4.4 SPLIT MULTIPLE ELEMENTS
If a clause applies to multiple elements ("статьи 3, 5 и 7"), create separate objects for EACH element.

## 5. VERIFICATION

Before outputting:
- [ ] All dates in DD.MM.YYYY format
- [ ] `structural_element` follows hierarchy rules
- [ ] Multiple elements are split into individual objects
- [ ] `note_text` starts with "Действие положений [structural_element]"

## 6. EXAMPLES

See `examples/stage_2/characteristic_examples.json` for reference patterns.

## 7. ANTI-PATTERNS

See `examples/common/anti_patterns.json` for known failure modes.
