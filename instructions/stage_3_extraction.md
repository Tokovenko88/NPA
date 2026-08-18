# Stage 3: Changes Extraction

## 1. TASK

Transform the HTML text of a single article from the amending law into a strictly structured JSON array describing all changes to the target NPA.

## 2. INPUT

- `source_npa.json` — clean HTML of a SINGLE article from the amending law
- Target NPA context (number and structure)

## 3. OUTPUT FORMAT

Return a JSON array of objects:

```json
[
  {
    "revision_number": "1)->а)",
    "structural_element": "Статья 2 часть 3 пункт 3",
    "type": "delete",
    "description": "пункты 3 и 4 части 3 признать утратившими силу",
    "new": "пункт 3"
  }
]
```

Fields (strict order):
1. `revision_number` — hierarchy of internal sub-items via `->` (e.g., `"1)->а)"`), or `null` if no internal numbering
2. `structural_element` — path to the changed/added element
3. `type` — one of: `"add"`, `"delete"`, `"change"`, `"new_redaction"`
4. `description` — verbatim HTML fragment + instruction for change/delete; absolute paragraph numbers for new_redaction/add
5. `new` — ONLY for `type = "add"`: name of the added element

## 4. CRITICAL RULES

### 4.1 REVISION_NUMBER
- `revision_number` = internal sub-item hierarchy of the SOURCE article (1), 2), a), b), etc.)
- NEVER include the source article number (it is a container, not a revision_number)
- NEVER include references to target NPA elements

### 4.2 TYPE CLASSIFICATION (apply in strict order)

**Step 0:** If the object is a sentence ("предложение") or table part ("строка", "ячейка", "графа") → `type = "change"` ALWAYS

**Step 1:** If "изложить в следующей редакции" applies to the NPA head ("наименование" without specifying words/sentences) → `type = "new_redaction"`

**Step 2:** If the verb applies to a whole structural element number with deletion verbs ("признать утратившим силу", "исключить") → `type = "delete"`
- Exception: if words/sentences/table parts are the object → `type = "change"`

**Step 3:** If "изложить в следующей редакции" applies to a WHOLE structural element → `type = "new_redaction"`
- Exception: if the object is a sentence or table part → `type = "change"`

**Step 4:** If "дополнить [element type] [number]" adds a new independent element → `type = "add"`
- Exception: table parts (row, cell, column) → `type = "change"`

**Step 5:** Everything else → `type = "change"`

### 4.3 SPLITTING RULES

**For delete:** Plural nouns with list/range ("пункты 3 и 4", "абзацы 1-3") MUST be split into individual objects.

**For new_redaction/add:** If the instruction names multiple elements ("пункты 1-4"), split into individual objects.

### 4.4 DESCRIPTION FORMAT

**For change/delete:**
- Full verbatim HTML fragment + instruction without parent context
- Example: `"второе предложение изложить в следующей редакции: Кандидаты, не заявившие о самоотводе..."`

**For new_redaction/add:**
- ONLY absolute paragraph numbers (e.g., `"5"`, `"5-7"`, `"5,7"`)
- NO HTML tags
- Paragraphs are numbered from top to bottom within the current sub-item

### 4.5 STRUCTURAL ELEMENT FORMAT

- Nominative case only
- Arabic numerals for numbered elements
- Roman numerals and superscript signs preserved verbatim
- Order: highest level to lowest level
- NEVER include "предложение", "строка", "ячейка", "графа" in structural_element

### 4.6 STRUCTURE CHANGE RESTRICTION

**STRICT PROHIBITION:** The AI agent has NO authority to modify the structure of the target NPA unless the amending NPA explicitly instructs such changes.

- Only elements/operations explicitly mentioned in the amending NPA may be added, deleted, or reorganized.
- The agent must NOT add, remove, or rearrange child elements based on assumptions, inference, or structural alignment with the amending NPA.
- If the amending NPA provides a new redaction of an article, the agent must replace ONLY the content of that article; it must NOT add or remove child elements unless the amending NPA explicitly says so (e.g., "дополнить статьей", "статью X исключить").
- The target NPA structure is immutable unless the amending NPA explicitly modifies it.

## 5. SELF-VALIDATION CHECKLIST

Before writing each object:
- [ ] `revision_number` does not contain the source article number
- [ ] `type` matches the object and verb correctly
- [ ] `description` for change/delete contains full HTML, for new_redaction/add contains only numbers
- [ ] `structural_element` is in correct hierarchical order
- [ ] Plural deletes are split
- [ ] No invented numbers

## 6. EXAMPLES

See `examples/stage_3/characteristic_examples.json` for reference patterns.

## 7. ANTI-PATTERNS

See `examples/common/anti_patterns.json` for known failure modes.
