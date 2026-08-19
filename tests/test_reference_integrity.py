from npa_processor.domain.reference_integrity import (
    find_broken_child_refs,
    find_duplicate_item_ids,
    find_reference_issues,
)


def test_duplicate_item_ids_are_reported_without_mutation():
    data = {
        "npa_items_revision": [
            {"item_id": "article_1", "item_children": []},
            {"item_id": "article_1", "item_children": []},
        ]
    }

    issues = find_duplicate_item_ids(data)

    assert len(issues) == 1
    assert issues[0].category == "duplicate_item_id"
    assert issues[0].item_id == "article_1"
    assert data["npa_items_revision"][1]["item_id"] == "article_1"


def test_broken_child_ref_is_reported():
    data = {
        "npa_items_revision": [
            {
                "item_id": "article_1",
                "body": [{"type": "child_ref", "item_id": "missing_point"}],
                "item_children": [],
            }
        ]
    }

    issues = find_broken_child_refs(data)

    assert len(issues) == 1
    assert issues[0].category == "broken_child_ref"
    assert issues[0].reference == "missing_point"


def test_valid_child_ref_has_no_issue():
    data = {
        "npa_items_revision": [
            {
                "item_id": "article_1",
                "body": [{"type": "child_ref", "item_id": "point_1"}],
                "item_children": [{"item_id": "point_1", "item_children": []}],
            }
        ]
    }

    assert find_reference_issues(data) == []
