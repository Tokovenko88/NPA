"""Pure planning helpers for deterministic element rebuild order.

This module contains only deterministic planning logic. It does not mutate the
NPA document and does not execute a rebuild.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class RebuildPlan:
    """Immutable rebuild plan produced from a document and requested IDs."""

    item_ids: tuple[str, ...]
    parent_map: Mapping[str, str | None]


def build_parent_map(items: Iterable[Mapping]) -> dict[str, str | None]:
    """Return ``item_id -> parent_item_id`` for a nested NPA item sequence."""
    parent_map: dict[str, str | None] = {}

    def walk(children: Iterable[Mapping], parent_id: str | None = None) -> None:
        for item in children:
            if not isinstance(item, Mapping):
                continue
            item_id = item.get("item_id")
            normalized_id = str(item_id) if item_id else parent_id
            if item_id:
                parent_map[normalized_id] = parent_id
            nested = item.get("item_children", [])
            if isinstance(nested, (list, tuple)):
                walk(nested, normalized_id)

    walk(items)
    return parent_map


def ancestor_ids(item_id: str, parent_map: Mapping[str, str | None]) -> list[str]:
    """Return ancestors from the direct parent upwards, without cycles."""
    result: list[str] = []
    current = parent_map.get(item_id)
    seen: set[str] = {item_id}
    while current and current not in seen:
        result.append(current)
        seen.add(current)
        current = parent_map.get(current)
    return result


def rebuild_order(item_ids: Iterable[str], parent_map: Mapping[str, str | None]) -> list[str]:
    """Return requested IDs plus their ancestors in deterministic child-first order.

    A requested parent dominates requested descendants because rebuilding the
    parent covers its subtree. Ancestors of the effective set are appended
    so that dependent elements are ready before their children. Malformed
    cycles are cut by ``ancestor_ids``.
    """
    requested = {str(item_id) for item_id in item_ids if item_id}
    if not requested:
        return []

    effective = {
        item_id
        for item_id in requested
        if not any(ancestor in requested for ancestor in ancestor_ids(item_id, parent_map))
    }

    result_set: set[str] = set(effective)
    for item_id in effective:
        for ancestor in ancestor_ids(item_id, parent_map):
            if ancestor:
                result_set.add(ancestor)

    ancestors_by_id = {
        item_id: ancestor_ids(item_id, parent_map)
        for item_id in result_set
    }
    return sorted(
        result_set,
        key=lambda value: (-len(ancestors_by_id[value]), value),
    )


def build_rebuild_plan(document: Mapping, item_ids: Iterable[str]) -> RebuildPlan:
    """Build a validated, immutable rebuild plan for a document.

    Unknown IDs are ignored. The complete parent map is retained for runtime
    consumers so tree metadata is not reconstructed a second time.
    """
    roots = document.get("npa_items_revision", [])
    if not isinstance(roots, (list, tuple)):
        roots = []
    parent_map = build_parent_map(roots)
    requested = {str(item_id) for item_id in item_ids if item_id}
    valid_ids = (item_id for item_id in requested if item_id in parent_map)
    effective = {
        item_id
        for item_id in valid_ids
        if not any(ancestor in requested for ancestor in ancestor_ids(item_id, parent_map))
    }
    ordered = rebuild_order(effective, parent_map)
    ordered = [item_id for item_id in ordered if item_id in effective]
    return RebuildPlan(
        tuple(ordered),
        MappingProxyType(parent_map),
    )
