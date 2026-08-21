"""Recursive revision-tree synchronization for NPA documents.

When a parent element receives a new revision (e.g. ``new_redaction``) at date
``T``, every child referenced in that revision's body must itself have a revision
that is effective at ``T``.  Without this, the tree is temporally inconsistent:
the parent claims a new state at ``T`` while its children still reflect an older
state (``stale_child_revision``).

This module provides:

* ``get_effective_revision(item, date)`` — the canonical helper that returns the
  revision of *item* effective on *date*, or ``None``.
* ``get_latest_revision(item)`` — the revision with the greatest ``valid_from``.
* ``sync_revision_tree(data, change_date, modified_by_id, log_callback)`` — walks
  the tree and materialises a new revision at ``change_date`` for every child
  referenced in a revision dated ``change_date`` that does not yet have an
  effective revision on that date.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Callable, Optional

from npa_processor.processing.text_utils import (
    close_revision_date,
    get_active_revision,
)
from npa_processor.processing.tree_utils import find_item_by_id


_DATE_FORMAT = "%d.%m.%Y"


def _parse_date(value: Any) -> Optional[datetime]:
    """Parse a DD.MM.YYYY string into a ``datetime`` (date at midnight)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value).strip(), _DATE_FORMAT)
    except (ValueError, TypeError):
        return None


def get_effective_revision(item: dict, date: Any) -> Optional[dict]:
    """Return the revision of *item* that is effective on *date*.

    A revision is effective when ``valid_from <= date`` and (``valid_to`` is
    ``None`` or ``date <= valid_to``).  When several revisions qualify, the one
    with the greatest ``valid_from`` wins.  Returns ``None`` when no revision
    covers *date*.

    The rule is intentionally date-based: it never relies on element order,
    array index, ``mod_type`` or insertion position.
    """
    if not isinstance(item, dict):
        return None
    target = _parse_date(date)
    if target is None:
        return None
    best: Optional[dict] = None
    best_vf: Optional[datetime] = None
    for rev in item.get("revisions", []):
        vf = _parse_date(rev.get("valid_from"))
        if vf is None or vf > target:
            continue
        vt = _parse_date(rev.get("valid_to"))
        if vt is not None and target > vt:
            continue
        if best_vf is None or vf > best_vf:
            best = rev
            best_vf = vf
    return best


def get_latest_revision(item: dict) -> Optional[dict]:
    """Return the revision of *item* with the greatest ``valid_from``."""
    if not isinstance(item, dict):
        return None
    best: Optional[dict] = None
    best_vf: Optional[datetime] = None
    for rev in item.get("revisions", []):
        vf = _parse_date(rev.get("valid_from"))
        if vf is None:
            continue
        if best_vf is None or vf > best_vf:
            best = rev
            best_vf = vf
    return best


def _has_effective_revision(item: dict, date: Any) -> bool:
    return get_effective_revision(item, date) is not None


def sync_revision_tree(
    data: dict,
    change_date: str,
    modified_by_id: str,
    log_callback: Optional[Callable[[str, str], None]] = None,
) -> int:
    """Ensure every child referenced in a revision at ``change_date`` has an
    effective revision on ``change_date``.

    For each item, for each of its revisions whose ``valid_from`` equals
    *change_date*, inspect the ``child_ref`` blocks in that revision's body.
    If the referenced child has no effective revision on *change_date*, close
    the child's currently-active revision (``valid_to = change_date - 1 day``)
    and append a new revision dated *change_date* that copies the child's
    latest body.  The operation recurses into children so the whole subtree
    under a re-dated parent is aligned.

    Returns the number of new revisions materialised.
    """
    if not isinstance(data, dict):
        return 0

    change_dt = _parse_date(change_date)
    if change_dt is None:
        return 0
    if isinstance(change_date, str):
        change_date_str = change_date.strip()
    else:
        change_date_str = change_dt.strftime(_DATE_FORMAT)

    created = 0

    def _log(msg: str, tag: str = "info") -> None:
        if log_callback:
            log_callback(msg, tag)

    def _materialise(child: dict) -> bool:
        """Create a revision at ``change_date`` for *child`` if its latest
        revision predates ``change_date``."""
        latest = get_latest_revision(child)
        if latest is None:
            return False
        latest_vf = _parse_date(latest.get("valid_from"))
        if latest_vf is None:
            return False
        if latest_vf >= change_dt:
            return False  # child already has a revision at/after change_date
        # Child is stale: close its currently-active revision and materialise
        # a new one at change_date that preserves the latest body.
        active = get_active_revision(child)
        if active is not None:
            active["valid_to"] = close_revision_date(change_date_str)
        new_rev = {
            "body": copy.deepcopy(latest.get("body", [])),
            "mod_type": "change",
            "modified_by_id": modified_by_id,
            "valid_from": change_date_str,
        }
        child.setdefault("revisions", []).append(new_rev)
        return True

    def _process_item(item: dict) -> None:
        nonlocal created
        for rev in item.get("revisions", []):
            if rev.get("valid_from") != change_date_str:
                continue
            for block in rev.get("body", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "child_ref":
                    continue
                child_id = block.get("item_id")
                if not child_id:
                    continue
                child = find_item_by_id(data, child_id)
                if child is None:
                    continue
                if _materialise(child):
                    created += 1
                    _log(
                        f"  SYNC-TREE: materialised revision at {change_date_str} "
                        f"for child {child_id}",
                        "info",
                    )

    def _walk(items: list) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            _process_item(item)
            _walk(item.get("item_children", []))

    _walk(data.get("npa_items_revision", []))
    return created
