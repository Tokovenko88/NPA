"""Canonical date handling for NPA processing.

External NPA data may arrive as DD.MM.YYYY or ISO YYYY-MM-DD.  The rest of the
pipeline should work with ``datetime.date`` values and only format at I/O
boundaries.  This module deliberately does not silently invent dates.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

_INPUT_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y")
_OUTPUT_FORMAT = "%d.%m.%Y"


def parse_npa_date(value: object, *, field_name: str = "date") -> Optional[date]:
    """Parse a supported NPA date representation.

    ``None`` and an empty string are treated as missing. Invalid non-empty
    values raise ``ValueError`` rather than being silently replaced.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    for fmt in _INPUT_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid {field_name}: {value!r}; expected DD.MM.YYYY or YYYY-MM-DD")


def format_npa_date(value: object, *, field_name: str = "date") -> str:
    """Format a date using the canonical external NPA representation."""
    parsed = parse_npa_date(value, field_name=field_name)
    if parsed is None:
        return ""
    return parsed.strftime(_OUTPUT_FORMAT)


def format_npa_date_iso(value: object, *, field_name: str = "date") -> str:
    """Format a date for storage/interchange in ISO YYYY-MM-DD form."""
    parsed = parse_npa_date(value, field_name=field_name)
    if parsed is None:
        return ""
    return parsed.isoformat()
