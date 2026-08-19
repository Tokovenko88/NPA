from npa_processor.domain import (
    ancestor_ids,
    build_parent_map,
    find_reference_issues,
    format_npa_date,
    parse_npa_date,
    rebuild_order,
)


def test_domain_package_exposes_canonical_helpers():
    parents = build_parent_map(
        [{"item_id": "article_1", "item_children": [{"item_id": "point_1"}]}]
    )

    assert ancestor_ids("point_1", parents) == ["article_1"]
    assert rebuild_order(["point_1"], parents) == ["point_1", "article_1"]
    assert format_npa_date(parse_npa_date("2026-08-19")) == "19.08.2026"


def test_reference_integrity_is_available_from_domain_api():
    data = {
        "npa_items_revision": [
            {"item_id": "article_1", "revisions": [{"body": []}]},
            {"item_id": "article_1", "revisions": [{"body": []}]},
        ]
    }

    issues = find_reference_issues(data)

    assert any(issue.code == "duplicate_item_id" for issue in issues)
