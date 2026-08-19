from npa_processor.domain.rebuild_plan import ancestor_ids, build_parent_map, rebuild_order


def test_build_parent_map_and_ancestors():
    items = [
        {
            "item_id": "article_1",
            "item_children": [
                {"item_id": "point_1", "item_children": [{"item_id": "paragraph_1"}]},
            ],
        }
    ]

    parents = build_parent_map(items)

    assert parents == {
        "article_1": None,
        "point_1": "article_1",
        "paragraph_1": "point_1",
    }
    assert ancestor_ids("paragraph_1", parents) == ["point_1", "article_1"]


def test_rebuild_order_is_deepest_first_and_includes_ancestors():
    items = [
        {
            "item_id": "article_2",
            "item_children": [{"item_id": "point_2"}],
        },
        {
            "item_id": "article_1",
            "item_children": [{"item_id": "point_1"}],
        },
    ]
    parents = build_parent_map(items)

    assert rebuild_order(["point_1", "point_2"], parents) == [
        "point_1",
        "point_2",
        "article_1",
        "article_2",
    ]


def test_rebuild_order_handles_parent_cycle_without_looping():
    parents = {"a": "b", "b": "a"}

    assert rebuild_order(["a"], parents) == ["a", "b"]
