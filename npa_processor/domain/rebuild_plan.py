"""Pure planning helpers for deterministic element rebuild order.

The pipeline historically calculated parent/ancestor ordering inline in
``scripts/run_pipeline.py``.  This module contains only the deterministic
planning part; it does not mutate the document and does not perform a rebuild.
That separation makes the ordering logic testable before it is wired into the
runtime rebuild engine.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def build_parent_map(items: Iterable[Mapping]) -> dict[str, str | None]:
    """Return ``item_id -> parent_item_id`` for a nested NPA item sequence."""
    parent_map: dict[str, str | None] = {}

    def walk(children: Iterable[Mapping], parent_id: str | None = None) -> None:
        for item in children:
            if not isinstance(item, Mapping):
                continue
            item_id = item.get("item_id")
            if item_id:
                parent_map[str(item_id)] = parent_id
            nested = item.get("item_children", [])
            if isinstance(nested, list):
                walk(nested, str(item_id) if item_id else parent_id)

    walk(items)
    return parent_map


def ancestor_ids(item_id: str, parent_map: Mapping[str, str | None]) -> list[str]:
    """Return ancestors from the direct parent upwards, without cycles."""
    result: list[str] = []
    current = parent_map.get(item_id)
    seen: set[str] = set()
    while current and current not in seen:
        result.append(current)
        seen.add(current)
        current = parent_map.get(current)
    return result


def rebuild_order(item_ids: Iterable[str], parent_map: Mapping[str, str | None]) -> list[str]:
    """Return a deterministic child-first order including required ancestors.

    Duplicates are removed while preserving the deepest-first ordering.  A
    malformed cycle is cut rather than looping forever.
    """
    required: set[str] = set()
    for item_id in item_ids:
        if not item_id:
            continue
        required.add(str(item_id))
        required.update(ancestor_ids(str(item_id), parent_map))

    def depth(item_id: str) -> int:
        return len(ancestor_ids(item_id, parent_map))

    return sorted(required, key=lambda value: (-depth(value), value))
