"""Public pipeline planning API.

CLI entry points remain in ``scripts/`` for compatibility. Planning itself
lives in the domain layer so there is a single canonical implementation.
"""

from npa_processor.domain.rebuild_plan import (
    RebuildPlan,
    ancestor_ids,
    build_parent_map,
    build_rebuild_plan,
    rebuild_order,
)

__all__ = [
    "RebuildPlan",
    "ancestor_ids",
    "build_parent_map",
    "build_rebuild_plan",
    "rebuild_order",
]
