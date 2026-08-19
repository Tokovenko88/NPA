from npa_processor.processing.element_finder import find_item_by_revision_number


def test_find_item_by_revision_number_uses_canonical_path_parser():
    data = {
        "npa_items_revision": [
            {
                "item_id": "article-1",
                "item_number": "1",
                "item_children": [
                    {
                        "item_id": "point-1-2",
                        "item_number": "2",
                        "item_children": [],
                    }
                ],
            }
        ]
    }

    assert find_item_by_revision_number(data, "статья 1 -> пункт 2") == "point-1-2"


def test_find_item_by_revision_number_respects_context_root():
    data = {
        "npa_items_revision": [
            {
                "item_id": "outside",
                "item_number": "1",
                "item_children": [],
            }
        ]
    }
    context_root = {
        "item_id": "article-10",
        "item_children": [
            {
                "item_id": "point-3",
                "item_number": "3",
                "item_children": [],
            }
        ],
    }

    assert find_item_by_revision_number(data, "пункт 3", context_root=context_root) == "point-3"
