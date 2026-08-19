"""Pipeline orchestration primitives.

The package contains deterministic planning and runtime coordination helpers.
CLI entry points remain in ``scripts/`` for compatibility.
"""

from npa_processor.pipeline.rebuild import (
    RebuildPlan,
    build_rebuild_plan,
    collect_pending_ids,
    execute_rebuild_plan,
    merge_rebuild_ids,
)

__all__ = [
    "RebuildPlan",
    "build_rebuild_plan",
    "collect_pending_ids",
    "execute_rebuild_plan",
    "merge_rebuild_ids",
]
