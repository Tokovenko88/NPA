"""Non-destructive integrity checks for NPA item identifiers and references.

These checks deliberately report problems instead of repairing them.  Changing
an ``item_id`` or silently deleting a broken ``child_ref`` can invalidate other
references and history, so repair must be an explicit, context-aware operation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceIssue:
    """A single structural reference integrity problem."""

    category: str
    message: str
    item_id: str | None = None
    reference: str | None = None


def walk_items(data: Mapping) -> Iterable[Mapping]:
    """Yield all nested NPA items without mutating the document."""
    root = data.get("npa_items_revision", [])

    def walk(items: object):
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, Mapping):
                continue
            yield item
            yield from walk(item.get("item_children", []))

    yield from walk(root)


def find_duplicate_item_ids(data: Mapping) -> list[ReferenceIssue]:
    """Report duplicate item IDs; never rename them."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in walk_items(data):
        item_id = item.get("item_id")
        if not item_id:
            continue
        item_id = str(item_id)
        if item_id in seen:
            duplicates.add(item_id)
        seen.add(item_id)

    return [
        ReferenceIssue(
            category="duplicate_item_id",
            message=f"Duplicate item_id: {item_id}",
            item_id=item_id,
        )
        for item_id in sorted(duplicates)
    ]


def find_broken_child_refs(data: Mapping) -> list[ReferenceIssue]:
    """Report child references that point to no existing item."""
    known_ids = {
        str(item["item_id"])
        for item in walk_items(data)
        if item.get("item_id")
    }
    issues: list[ReferenceIssue] = []

    for item in walk_items(data):
        item_id = str(item.get("item_id", "")) or None
        body = item.get("body", [])
        if not isinstance(body, list):
            continue
        for block in body:
            if not isinstance(block, Mapping) or block.get("type") != "child_ref":
                continue
            reference = block.get("item_id") or block.get("ref_item_id")
            if reference and str(reference) not in known_ids:
                issues.append(
                    ReferenceIssue(
                        category="broken_child_ref",
                        message=f"Broken child_ref: {reference}",
                        item_id=item_id,
                        reference=str(reference),
                    )
                )

    return issues


def find_reference_issues(data: Mapping) -> list[ReferenceIssue]:
    """Return all non-destructive item-ID/reference integrity issues."""
    return find_duplicate_item_ids(data) + find_broken_child_refs(data)
