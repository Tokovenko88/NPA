"""Non-destructive preflight checks for pipeline inputs.

The preflight layer validates conditions that are unsafe to repair implicitly:
source dates and item/reference identity.  It returns structured issues and
never mutates the supplied documents.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from npa_processor.domain.dates import parse_npa_date
from npa_processor.domain.reference_integrity import find_reference_issues


@dataclass(frozen=True)
class PreflightIssue:
    """A blocking or informational preflight issue."""

    category: str
    message: str
    field: str | None = None


def validate_source_dates(source: Mapping) -> list[PreflightIssue]:
    """Validate the source date fields without inventing a fallback date."""
    issues: list[PreflightIssue] = []
    value = source.get("valid_from") or source.get("date_signed")
    if value in (None, ""):
        issues.append(
            PreflightIssue(
                category="source_date_missing",
                message="Source NPA has neither valid_from nor date_signed",
                field="valid_from",
            )
        )
        return issues

    try:
        parse_npa_date(value, field_name="source valid_from/date_signed")
    except ValueError as exc:
        issues.append(
            PreflightIssue(
                category="source_date_invalid",
                message=str(exc),
                field="valid_from",
            )
        )
    return issues


def validate_document(data: Mapping) -> list[PreflightIssue]:
    """Run non-destructive structural/reference checks for a document."""
    issues = [
        PreflightIssue(issue.category, issue.message, issue.item_id or issue.reference)
        for issue in find_reference_issues(data)
    ]
    return issues


def run_preflight(source: Mapping, target: Mapping) -> list[PreflightIssue]:
    """Run all blocking preflight checks for source and target documents."""
    return validate_source_dates(source) + validate_document(target)
