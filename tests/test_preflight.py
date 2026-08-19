from npa_processor.domain import run_preflight, validate_source_dates


def test_missing_source_date_is_blocking():
    issues = validate_source_dates({})

    assert [(issue.category, issue.field) for issue in issues] == [
        ("source_date_missing", "valid_from")
    ]


def test_invalid_source_date_is_reported_without_fallback():
    issues = validate_source_dates({"valid_from": "not-a-date"})

    assert len(issues) == 1
    assert issues[0].category == "source_date_invalid"
    assert "not-a-date" in issues[0].message


def test_preflight_detects_duplicate_target_ids_without_mutation():
    target = {
        "npa_items_revision": [
            {"item_id": "article_1", "item_children": []},
            {"item_id": "article_1", "item_children": []},
        ]
    }

    issues = run_preflight({"valid_from": "19.08.2026"}, target)

    assert any(issue.category == "duplicate_item_id" for issue in issues)
    assert target["npa_items_revision"][1]["item_id"] == "article_1"
