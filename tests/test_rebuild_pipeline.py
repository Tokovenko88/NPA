import pytest

from npa_processor.domain.rebuild_plan import build_rebuild_plan as domain_build_rebuild_plan
from npa_processor.pipeline import build_rebuild_plan


def _document():
    return {
        "npa_items_revision": [
            {
                "item_id": "article_1",
                "item_children": [
                    {
                        "item_id": "article_1_part_1",
                        "item_children": [
                            {"item_id": "article_1_part_1_point_1", "item_children": []},
                            {"item_id": "article_1_part_1_point_2", "item_children": []},
                        ],
                    },
                ],
            },
        ]
    }


def test_pipeline_exports_canonical_domain_planner():
    assert build_rebuild_plan is domain_build_rebuild_plan


def test_rebuild_plan_is_deepest_first_and_deduplicated():
    plan = build_rebuild_plan(
        _document(),
        [
            "article_1_part_1_point_1",
            "article_1_part_1_point_1",
            "article_1_part_1_point_2",
        ],
    )

    assert plan.item_ids == (
        "article_1_part_1_point_1",
        "article_1_part_1_point_2",
    )


def test_unknown_ids_are_not_added_to_plan():
    plan = build_rebuild_plan(_document(), ["missing", "article_1"])
    assert plan.item_ids == ("article_1",)


def test_parent_request_dominates_descendant_request():
    plan = build_rebuild_plan(
        _document(),
        ["article_1", "article_1_part_1", "article_1_part_1_point_1"],
    )
    assert plan.item_ids == ("article_1",)


def test_parent_map_is_exposed_for_runtime_coordinator():
    plan = build_rebuild_plan(_document(), ["article_1_part_1"])
    assert plan.parent_map["article_1"] is None
    assert plan.parent_map["article_1_part_1"] == "article_1"
    assert plan.parent_map["article_1_part_1_point_1"] == "article_1_part_1"


def test_rebuild_plan_parent_map_is_read_only():
    plan = build_rebuild_plan(_document(), ["article_1"])

    with pytest.raises(TypeError):
        plan.parent_map["article_1"] = "unexpected-parent"
