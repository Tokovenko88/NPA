"""Domain-level APIs for deterministic, side-effect-free NPA processing."""

from npa_processor.domain.dates import (
    format_npa_date,
    format_npa_date_iso,
    parse_npa_date,
)
from npa_processor.domain.element_types import TYPE_TO_RUSSIAN, normalize_ru_type
from npa_processor.domain.preflight import PreflightIssue, run_preflight, validate_document, validate_source_dates
from npa_processor.domain.rebuild_plan import ancestor_ids, build_parent_map, rebuild_order
from npa_processor.domain.reference_integrity import find_reference_issues

__all__ = [
    "TYPE_TO_RUSSIAN",
    "PreflightIssue",
    "ancestor_ids",
    "build_parent_map",
    "find_reference_issues",
    "format_npa_date",
    "format_npa_date_iso",
    "normalize_ru_type",
    "parse_npa_date",
    "rebuild_order",
    "run_preflight",
    "validate_document",
    "validate_source_dates",
]
