"""Structural element identity helpers.

Provides a single source of truth for deciding whether an old child element
is a true content-continuation of a new child element.  Identity is defined
as matching across:

  * item_type
  * normalized item_number
  * active head text (after structural-prefix stripping)
  * canonical body (after HTML normalisation)
  * recursively identical children

A bare match on ``(item_type, item_number)`` is explicitly *not* enough.
"""

from __future__ import annotations

from npa_processor.processing.text_utils import (
    clean_head_text,
    clean_html_text,
    normalize_item_number,
)


def _canonical_body_paragraphs(element):
    rev = element.get('revisions', [])
    active_rev = None
    for r in reversed(rev):
        if r.get('valid_to') in (None, ''):
            active_rev = r
            break
    if active_rev is None and rev:
        active_rev = rev[-1]
    if active_rev is None:
        return ()
    body = active_rev.get('body', []) or []
    paragraphs = []
    for block in body:
        if block.get('type') != 'paragraph':
            continue
        html = block.get('html_text', '') or ''
        text = clean_html_text(html)
        if text:
            paragraphs.append(text)
    return tuple(paragraphs)


def _canonical_children(element):
    children = element.get('item_children', []) or []
    return tuple(
        (child.get('item_type'), normalize_item_number(child.get('item_type'), child.get('item_number')), _canonical_body_paragraphs(child), _canonical_children(child))
        for child in children
    )


def _active_head_text(element):
    head_revs = element.get('head_revisions', []) or []
    for rev in reversed(head_revs):
        if rev.get('valid_to') in (None, ''):
            return rev.get('head_text', '') or ''
    if head_revs:
        return head_revs[-1].get('head_text', '') or ''
    return ''


def are_structural_elements_identical(old_element, new_element):
    if not isinstance(old_element, dict) or not isinstance(new_element, dict):
        return False

    if old_element.get('item_type') != new_element.get('item_type'):
        return False

    old_number = normalize_item_number(old_element.get('item_type'), old_element.get('item_number'))
    new_number = normalize_item_number(new_element.get('item_type'), new_element.get('item_number'))
    if old_number != new_number:
        return False

    old_head = _active_head_text(old_element)
    new_head = _active_head_text(new_element)
    if old_head and new_head:
        item_type = old_element.get('item_type', '')
        item_number = str(old_element.get('item_number', ''))
        old_head_clean = clean_head_text(old_head, item_type, item_number)
        new_head_clean = clean_head_text(new_head, item_type, item_number)
        if old_head_clean != new_head_clean:
            return False

    old_body = _canonical_body_paragraphs(old_element)
    new_body = _canonical_body_paragraphs(new_element)
    if old_body != new_body:
        return False

    old_children = _canonical_children(old_element)
    new_children = _canonical_children(new_element)

    return old_children == new_children
