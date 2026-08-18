# Stage 4: HTML Text Processing

## 1. TASK

Apply text modifications to target element HTML and calculate precise coordinates for all changes (highlights).

## 2. INPUT

- `target_html` — current HTML of the target element
- `change_description` — verbal instruction describing the change (e.g., "слова A заменить словами B")

## 3. OUTPUT FORMAT

Return EXACTLY this JSON structure:

```json
{
  "html": "modified_html_content",
  "highlights": {
    "previous_edition": {
      "deletion": [{"text": "...", "positions": "M-N,M-N"}],
      "difference": [{"text": "...", "positions": "M-N"}]
    },
    "current_edition": {
      "addition": [{"text": "...", "positions": "M-N"}],
      "difference": [{"text": "...", "positions": "M-N"}]
    }
  }
}
```

## 4. CRITICAL RULES

### 4.1 NO CHARACTER COUNTING
Use strictly left-to-right occurrence index (N). 1st match = N=1, 2nd = N=2, etc.

### 4.2 WHOLE PHRASE MATCHING
Index N is determined strictly by the FULL target text, not substrings.

### 4.3 SEQUENTIAL PROCESSING
Process instructions sequentially. After each instruction, `working_html` is updated.

### 4.4 INSTRUCTION INDEPENDENCE
Each instruction has its own anchor text and insertion point. NEVER infer position from another instruction.

### 4.5 POSITION FORMAT
- `M-N` where M = paragraph number, N = occurrence index within paragraph
- Multiple positions separated by comma: `"1-1,1-2"`

### 4.6 AGGREGATION RULES
- Group records by `(instruction_num, text)`
- Merge positions within each group using comma
- NEVER merge different texts (including different grammatical cases)
- Table difference records MUST NEVER be merged via comma

## 5. PROCESSING ALGORITHM

### 5.1 TEXT MODE
1. Identify target paragraphs (all `<p>` tags, or specific paragraph if "в абзаце [M]")
2. For each instruction:
   a. Pass 1: Calculate coordinates, mask found text with `###MARKER_i###`
   b. Pass 2: Replace markers with new text or empty string
3. Aggregate results

### 5.2 TABLE MODE
1. Identify target rows
2. For each instruction:
   a. Calculate row indices
   b. Execute HTML row operations
3. Aggregate results

## 6. EXAMPLES

See `examples/stage_4/characteristic_examples.json` for deterministic processing examples.

## 7. ANTI-PATTERNS

See `examples/common/anti_patterns.json` for known failure modes.
