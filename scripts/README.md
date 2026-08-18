# Work Tools

## npa_helper.py
Utility functions for NPA JSON processing:
- `load_json(path)` - Load JSON with UTF-8 encoding
- `save_json(path, data)` - Save JSON with UTF-8 encoding and Russian support
- `date_add_days(date_str, days)` - Add days to a date string (DD.MM.YYYY)
- `get_active_revision(item)` - Get the active revision of an item
- `close_revision_and_create_new(...)` - Close current revision and create new one

## Usage
```python
from npa_helper import load_json, save_json, close_revision_and_create_new

item = load_json('path/to/item.json')
close_revision_and_create_new(item, '20.01.2025', 'change', '380')
save_json('path/to/item.json', item)
```
