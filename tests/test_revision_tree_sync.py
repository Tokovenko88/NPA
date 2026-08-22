"""Regression tests for recursive revision-tree synchronization.

These tests cover the core bug (article 4 stale children under a parent
``new_redaction``) and the related acceptance scenarios from the TЗ.
"""

import json
import os

import pytest

from npa_processor.learning import StructureVerifier
from npa_processor.processing.revision_tree_sync import (
    get_effective_revision,
    get_latest_revision,
    sync_revision_tree,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "work", "results")
RESULT_FILE = os.path.join(DATA_DIR, "269_2016_07_27_izm_380_2017_12_04.json")


def _load_result():
    with open(RESULT_FILE, encoding="utf-8") as f:
        return json.load(f)


def _find_item(items, item_id):
    for it in items:
        if it.get("item_id") == item_id:
            return it
        r = _find_item(it.get("item_children", []), item_id)
        if r:
            return r
    return None


def _error_categories(result):
    return [e.category for e in result.errors]


# ---------------------------------------------------------------------------
# Fixtures that deep-copy the shared result so tests stay independent.
# ---------------------------------------------------------------------------


@pytest.fixture
def result_data():
    return _load_result()


# ---------------------------------------------------------------------------
# 1. get_effective_revision behaviour
# ---------------------------------------------------------------------------


def test_effective_revision_picks_matching_revision():
    item = {
        "revisions": [
            {"valid_from": "08.08.2016", "valid_to": "14.12.2017", "body": "old"},
            {"valid_from": "15.12.2017", "valid_to": None, "body": "new"},
        ]
    }
    assert get_effective_revision(item, "14.12.2017")["body"] == "old"
    assert get_effective_revision(item, "15.12.2017")["body"] == "new"
    assert get_effective_revision(item, "08.08.2016")["body"] == "old"


def test_effective_revision_none_before_all_and_between_gaps():
    item = {
        "revisions": [
            {"valid_from": "08.08.2016", "valid_to": "14.12.2017", "body": "old"},
        ]
    }
    assert get_effective_revision(item, "01.01.2016") is None
    # valid_to is exclusive boundary: 14.12.2017 is still covered (<=)
    assert get_effective_revision(item, "14.12.2017")["body"] == "old"
    # after valid_to -> not covered
    assert get_effective_revision(item, "15.12.2017") is None


def test_effective_revision_most_recent_wins_among_candidates():
    item = {
        "revisions": [
            {"valid_from": "01.01.2016", "valid_to": None, "body": "first"},
            {"valid_from": "08.08.2016", "valid_to": None, "body": "second"},
        ]
    }
    assert get_effective_revision(item, "15.12.2017")["body"] == "second"


# ---------------------------------------------------------------------------
# 2. sync_revision_tree: the article 4 bug
# ---------------------------------------------------------------------------


def test_article_4_stale_children_detected_by_verifier(result_data):
    """Article 4 must be temporally consistent after the pipeline run.

    Regression: previously part_1/part_2/articles 5.x children were left with
    valid_from ``08.08.2016`` while the parent was a ``new_redaction`` dated
    ``15.12.2017``, producing ``stale_child_revision``.  The correct pipeline
    now materialises their revisions at the amendment date during tree
    reconciliation, so the verifier must find no stale children.
    """
    v = StructureVerifier()
    result = v.verify(result_data)
    cats = _error_categories(result)
    assert "stale_child_revision" not in cats
    assert "revision_child_missing" not in cats
    assert result.passed is True


def test_sync_fixes_article_4_recursive(result_data):
    """part_1/part_2 and part points already carry a 15.12.2017 revision.

    Re-running the synchroniser on a consistent tree must not create duplicates
    (idempotency), and every child referenced from the article's new revision
    must be effective on 15.12.2017.
    """
    part1 = _find_item(result_data["npa_items_revision"], "16012_article_4_part_1")
    part2 = _find_item(result_data["npa_items_revision"], "16012_article_4_part_2")
    assert get_latest_revision(part1)["valid_from"] == "15.12.2017"
    assert get_latest_revision(part2)["valid_from"] == "15.12.2017"

    before1 = len(part1.get("revisions", []))
    created = sync_revision_tree(result_data, "15.12.2017", "33699_article_1_point_5")
    # Дерево уже согласовано: ничего материализовывать не нужно.
    assert created == 0
    assert len(part1.get("revisions", [])) == before1

    for n in range(1, 6):
        pid = f"16012_article_4_part_1_point_{n}"
        p = _find_item(result_data["npa_items_revision"], pid)
        assert get_latest_revision(p)["valid_from"] == "15.12.2017"


def test_after_sync_verifier_passes(result_data):
    sync_revision_tree(result_data, "15.12.2017", "33699_article_1_point_5")
    v = StructureVerifier()
    result = v.verify(result_data)
    cats = _error_categories(result)
    assert "stale_child_revision" not in cats
    assert "revision_child_missing" not in cats


def test_sync_preserves_historical_revision(result_data):
    """Исторические пункты статьи 4 (08.08.2016 → 14.12.2017) остаются в дереве.

    part_1 — элемент, созданный новой редакцией; у него существует только
    ревизия от 15.12.2017.  Бывшие прямые пункты статьи сохранились как
    исторические записи с valid_from = 08.08.2016 и закрыты 14.12.2017.
    """
    part1 = _find_item(result_data["npa_items_revision"], "16012_article_4_part_1")
    sync_revision_tree(result_data, "15.12.2017", "33699_article_1_point_5")
    assert get_effective_revision(part1, "15.12.2017")["valid_from"] == "15.12.2017"
    assert get_effective_revision(part1, "14.12.2017") is None

    old_point = _find_item(result_data["npa_items_revision"], "16012_article_4_point_1")
    assert old_point is not None
    assert get_effective_revision(old_point, "14.12.2017")["valid_from"] == "08.08.2016"
    assert get_effective_revision(old_point, "15.12.2017") is None


# ---------------------------------------------------------------------------
# 3. article 5 regression: already-correct tree must stay untouched
# ---------------------------------------------------------------------------


def test_article_5_tree_preserved(result_data):
    part1 = _find_item(result_data["npa_items_revision"], "16012_article_5_part_1")
    assert len(part1["revisions"]) == 2
    sync_revision_tree(result_data, "15.12.2017", "33699_article_1_point_5")
    # article 5 already had 15.12.2017 revisions -> unchanged
    assert len(part1["revisions"]) == 2
    assert get_latest_revision(part1)["valid_from"] == "15.12.2017"


# ---------------------------------------------------------------------------
# 4. effective_revision acceptance (point 48/49)
# ---------------------------------------------------------------------------


def test_effective_revision_article_4_part_1(result_data):
    # Элемент part_1 создан новой редакцией — на 14.12.2017 его не было.
    part1 = _find_item(result_data["npa_items_revision"], "16012_article_4_part_1")
    eff_new = get_effective_revision(part1, "15.12.2017")
    assert eff_new is not None
    assert eff_new["valid_from"] == "15.12.2017"
    assert get_effective_revision(part1, "14.12.2017") is None
    # Исторический пункт статьи 4 был активен до 14.12.2017 включительно.
    point1 = _find_item(result_data["npa_items_revision"], "16012_article_4_point_1")
    eff_old = get_effective_revision(point1, "14.12.2017")
    assert eff_old is not None
    assert eff_old["valid_from"] == "08.08.2016"
    assert get_effective_revision(point1, "15.12.2017") is None


# ---------------------------------------------------------------------------
# 5. stale-child synthetic fixture (point 26)
# ---------------------------------------------------------------------------


def test_synthetic_stale_child_detected():
    """Родительская ревизия ссылается на ребёнка, чья единственная ревизия уже
    закрыта до даты родителя — временное несоответствие обязано быть выявлено."""
    data = {
        "npa_items_revision": [
            {
                "item_id": "art_1",
                "item_type": "article",
                "item_number": "1",
                "item_level": 1,
                "revisions": [
                    {
                        "valid_from": "01.01.2020",
                        "valid_to": None,
                        "body": [{"type": "child_ref", "item_id": "pt_1", "order": 1}],
                    }
                ],
                "item_children": [
                    {
                        "item_id": "pt_1",
                        "item_type": "point",
                        "item_number": "1",
                        "item_level": 2,
                        "revisions": [
                            {"valid_from": "01.01.2019", "valid_to": "31.12.2019",
                             "body": [{"type": "paragraph", "html_text": "<p>x</p>", "order": 1}]}
                        ],
                        "item_children": [],
                    }
                ],
            }
        ]
    }
    v = StructureVerifier()
    result = v.verify(data)
    assert "stale_child_revision" in _error_categories(result)


def test_synthetic_inherited_open_child_passes():
    """Родительская ревизия ссылается на ребёнка с открытой (ненаследуемой)
    ревизией, начавшейся раньше даты родителя — корректное наследование,
    создавать «копию» ребёнка не требуется."""
    data = {
        "npa_items_revision": [
            {
                "item_id": "art_1",
                "item_type": "article",
                "item_number": "1",
                "item_level": 1,
                "revisions": [
                    {
                        "valid_from": "01.01.2020",
                        "valid_to": None,
                        "body": [{"type": "child_ref", "item_id": "pt_1", "order": 1}],
                    }
                ],
                "item_children": [
                    {
                        "item_id": "pt_1",
                        "item_type": "point",
                        "item_number": "1",
                        "item_level": 2,
                        "revisions": [
                            {"valid_from": "01.01.2019", "valid_to": None,
                             "body": [{"type": "paragraph", "html_text": "<p>x</p>", "order": 1}]}
                        ],
                        "item_children": [],
                    }
                ],
            }
        ]
    }
    v = StructureVerifier()
    result = v.verify(data)
    assert "stale_child_revision" not in _error_categories(result)


def test_synthetic_correct_historical_child_passes():
    """Parent and child both old, or both new -> no stale error."""
    data = {
        "npa_items_revision": [
            {
                "item_id": "art_1",
                "item_type": "article",
                "item_number": "1",
                "item_level": 1,
                "revisions": [
                    {"valid_from": "01.01.2016", "valid_to": "31.12.2016",
                     "body": [{"type": "child_ref", "item_id": "pt_1", "order": 1}]},
                    {"valid_from": "01.01.2017", "valid_to": None,
                     "body": [{"type": "child_ref", "item_id": "pt_1", "order": 1}]},
                ],
                "item_children": [
                    {
                        "item_id": "pt_1",
                        "item_type": "point",
                        "item_number": "1",
                        "item_level": 2,
                        "revisions": [
                            {"valid_from": "01.01.2016", "valid_to": "31.12.2016",
                             "body": [{"type": "paragraph", "html_text": "<p>x</p>", "order": 1}]},
                            {"valid_from": "01.01.2017", "valid_to": None,
                             "body": [{"type": "paragraph", "html_text": "<p>y</p>", "order": 1}]},
                        ],
                        "item_children": [],
                    }
                ],
            }
        ]
    }
    v = StructureVerifier()
    result = v.verify(data)
    assert "stale_child_revision" not in _error_categories(result)
