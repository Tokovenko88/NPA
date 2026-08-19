"""Deterministic Stage-4 text change engine for simple replacement patterns."""

import re

from npa_processor.processing.html_utils import (
    _extract_replacement_pairs,
    compute_highlights_from_html_diff,
)


def matches_deterministic_pattern(description):
    if not description:
        return False
    desc_lower = description.lower()
    patterns = [
        r'заменить\s+слова',
        r'слова\s+заменить',
        r'дополнить\s+словами',
        r'исключить\s+слова',
        r'слова\s+исключить',
    ]
    for pat in patterns:
        if re.search(pat, desc_lower):
            return True
    return False


def apply_deterministic_change(old_html, description, log_callback=None):
    replacement_pairs = _extract_replacement_pairs(description)
    if not replacement_pairs:
        return None, None

    new_html = old_html
    for old_text, new_text in replacement_pairs:
        if old_text in new_html:
            new_html = new_html.replace(old_text, new_text, 1)
        else:
            if log_callback:
                log_callback(
                    f"  Deterministic engine: text '{old_text[:40]}...' not found in HTML",
                    'warning'
                )
            return None, None

    if new_html == old_html:
        return None, None

    highlights = compute_highlights_from_html_diff(
        old_html, new_html, log_callback, change_description=description
    )
    return new_html, highlights
