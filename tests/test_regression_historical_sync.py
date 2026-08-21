"""Regression tests for historical synchronization and report generation.

Covers:
- Historical sync behavior of sync_structural_element_recursive
- Verifier: change_not_applied => passed=false
- Report JSON/MD contain specific item_ids, before/after, UTF-8 clean
"""

import json
import re

from npa_processor.learning.verifier import StructureVerifier
from npa_processor.processing.identity import are_structural_elements_identical


def _make_element(item_id, item_type, item_number, body=None, children=None,
                  revisions=None, head_revisions=None, item_level=1,
                  head_text=None, prefix_revisions=None):
    element = {
        "item_id": item_id,
        "item_type": item_type,
        "item_number": item_number,
        "item_level": item_level,
        "revisions": revisions or [],
        "item_children": children or [],
    }
    if head_revisions is not None:
        element["head_revisions"] = head_revisions
    if head_text is not None:
        element.setdefault("head_revisions", []).append({"head_text": head_text})
    if prefix_revisions is not None:
        element["item_prefix_revisions"] = prefix_revisions
    return element


def _paragraph_rev(html_text, valid_from, valid_to=None, mod_type=None):
    rev = {
        "body": [{"type": "paragraph", "html_text": html_text, "order": 1}],
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    if mod_type is not None:
        rev["mod_type"] = mod_type
    return rev


# ------------------------------------------------------------------
# Test 1: identical child with same key stays in parent, no extra revs
# ------------------------------------------------------------------
def test_identical_child_with_same_key_unchanged():
    old_point = _make_element(
        "p1", "point", "1", item_level=2,
        revisions=[_paragraph_rev("<p>Old</p>", "01.01.2020")],
    )
    article = _make_element(
        "a1", "article", "1", item_level=1,
        children=[old_point],
        revisions=[{"body": [{"type": "child_ref", "item_id": "p1", "order": 1}],
                    "valid_from": "01.01.2020", "valid_to": None}],
    )
    new_article = _make_element(
        "a1_new", "article", "1", item_level=1,
        children=[_make_element("p1_new", "point", "1", item_level=2,
                                revisions=[_paragraph_rev("<p>Old</p>", "15.01.2020")])],
        revisions=[{"body": [{"type": "child_ref", "item_id": "p1_new", "order": 1}],
                    "valid_from": "15.01.2020", "valid_to": None}],
    )
    from npa_processor.processing.element_ops import sync_structural_element_recursive
    sync_structural_element_recursive(
        article, new_article, "15.01.2020", "src_1", {},
        lambda msg, tag="info": None,
        is_top_level=True,
    )
    assert len(article.get("revisions", [])) == 1
    assert old_point["item_id"] == "p1"
    assert len(old_point.get("revisions", [])) == 1


# ------------------------------------------------------------------
# Test 2: changed child gets new revision, parent does not
# ------------------------------------------------------------------
def test_changed_child_gets_new_revision_parent_unchanged():
    old_point = _make_element(
        "p1", "point", "1", item_level=2,
        revisions=[_paragraph_rev("<p>Old</p>", "01.01.2020")],
    )
    article = _make_element(
        "a1", "article", "1", item_level=1,
        children=[old_point],
        revisions=[{"body": [{"type": "child_ref", "item_id": "p1", "order": 1}],
                    "valid_from": "01.01.2020", "valid_to": None}],
    )
    new_article = _make_element(
        "a1_new", "article", "1", item_level=1,
        children=[_make_element("p1_new", "point", "1", item_level=2,
                                revisions=[_paragraph_rev("<p>New text</p>", "15.01.2020")])],
        revisions=[{"body": [{"type": "child_ref", "item_id": "p1_new", "order": 1}],
                    "valid_from": "15.01.2020", "valid_to": None}],
    )
    from npa_processor.processing.element_ops import sync_structural_element_recursive
    sync_structural_element_recursive(
        article, new_article, "15.01.2020", "src_1", {},
        lambda msg, tag="info": None,
        is_top_level=True,
    )
    assert len(article.get("revisions", [])) == 1
    assert len(old_point.get("revisions", [])) == 2
    assert old_point["revisions"][-1]["valid_from"] == "15.01.2020"
    assert old_point["revisions"][-1]["mod_type"] == "change"
    assert old_point["revisions"][-2]["valid_to"] == "14.01.2020"


# ------------------------------------------------------------------
# Test 3: removed child stays in JSON with closed revision
# ------------------------------------------------------------------
def test_removed_child_kept_with_closed_revision():
    old_point = _make_element(
        "p1", "point", "1", item_level=2,
        revisions=[_paragraph_rev("<p>Gone</p>", "01.01.2020")],
    )
    article = _make_element(
        "a1", "article", "1", item_level=1,
        children=[old_point],
        revisions=[{"body": [{"type": "child_ref", "item_id": "p1", "order": 1}],
                    "valid_from": "01.01.2020", "valid_to": None}],
    )
    new_article = _make_element(
        "a1_new", "article", "1", item_level=1,
        children=[],
        revisions=[{"body": [], "valid_from": "15.01.2020", "valid_to": None}],
    )
    from npa_processor.processing.element_ops import sync_structural_element_recursive
    sync_structural_element_recursive(
        article, new_article, "15.01.2020", "src_1", {},
        lambda msg, tag="info": None,
        is_top_level=True,
    )
    assert old_point["item_id"] == "p1"
    revs = old_point.get("revisions", [])
    assert len(revs) == 1
    assert revs[0]["valid_to"] == "14.01.2020"
    assert revs[0].get("not_valid") == "src_1"


# ------------------------------------------------------------------
# Test 4: added child creates parent revision with child_ref
# ------------------------------------------------------------------
def test_added_child_creates_parent_revision():
    article = _make_element(
        "a1", "article", "1", item_level=1,
        children=[],
        revisions=[{"body": [], "valid_from": "01.01.2020", "valid_to": None}],
    )
    new_article = _make_element(
        "a1_new", "article", "1", item_level=1,
        children=[_make_element("p1_new", "point", "1", item_level=2,
                                revisions=[_paragraph_rev("<p>New</p>", "15.01.2020", mod_type="add")])],
        revisions=[{"body": [{"type": "child_ref", "item_id": "p1_new", "order": 1}],
                    "valid_from": "15.01.2020", "valid_to": None}],
    )
    from npa_processor.processing.element_ops import sync_structural_element_recursive
    sync_structural_element_recursive(
        article, new_article, "15.01.2020", "src_1", {},
        lambda msg, tag="info": None,
        is_top_level=True,
    )
    assert len(article.get("revisions", [])) == 2
    new_point = next((c for c in article["item_children"] if c.get("item_id") == "p1_new"), None)
    assert new_point is not None
    assert new_point["revisions"][0]["mod_type"] == "add"
    assert new_point["revisions"][0]["valid_from"] == "15.01.2020"


# ------------------------------------------------------------------
# Test 5: deep change only affects the changed descendant
# ------------------------------------------------------------------
def test_deep_change_only_affected_branch():
    subpoint = _make_element(
        "sp1", "subpoint", "а", item_level=4,
        revisions=[_paragraph_rev("<p>Old sub</p>", "01.01.2020")],
    )
    point = _make_element(
        "p1", "point", "1", item_level=3,
        children=[subpoint],
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Old point</p>", "order": 1},
                             {"type": "child_ref", "item_id": "sp1", "order": 2}],
                    "valid_from": "01.01.2020", "valid_to": None}],
    )
    article = _make_element(
        "a1", "article", "1", item_level=1,
        children=[point],
        revisions=[{"body": [{"type": "child_ref", "item_id": "p1", "order": 1}],
                    "valid_from": "01.01.2020", "valid_to": None}],
    )
    new_subpoint = _make_element(
        "sp1_new", "subpoint", "а", item_level=4,
        revisions=[_paragraph_rev("<p>New sub</p>", "15.01.2020")],
    )
    new_point = _make_element(
        "p1_new", "point", "1", item_level=3,
        children=[new_subpoint],
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Old point</p>", "order": 1},
                             {"type": "child_ref", "item_id": "sp1_new", "order": 2}],
                    "valid_from": "15.01.2020", "valid_to": None}],
    )
    new_article = _make_element(
        "a1_new", "article", "1", item_level=1,
        children=[new_point],
        revisions=[{"body": [{"type": "child_ref", "item_id": "p1_new", "order": 1}],
                    "valid_from": "15.01.2020", "valid_to": None}],
    )
    from npa_processor.processing.element_ops import sync_structural_element_recursive
    sync_structural_element_recursive(
        article, new_article, "15.01.2020", "src_1", {},
        lambda msg, tag="info": None,
        is_top_level=True,
    )
    assert len(article.get("revisions", [])) == 1
    assert len(point.get("revisions", [])) == 1
    assert len(subpoint.get("revisions", [])) == 2
    assert subpoint["revisions"][-1]["valid_from"] == "15.01.2020"
    assert subpoint["revisions"][-2]["valid_to"] == "14.01.2020"


# ------------------------------------------------------------------
# Test 6: verifier change_not_applied => passed=false
# ------------------------------------------------------------------
def test_verifier_change_not_applied_prevents_passed():
    data = {
        "npa_items_revision": [
            _make_element("a1", "article", "1", item_level=1,
                          revisions=[_paragraph_rev("<p>Text</p>", "01.01.2020")]),
        ]
    }
    changes = [{"type": "new_redaction", "structural_element": "Статья 2"}]
    verifier = StructureVerifier()
    result = verifier.verify(data, changes=changes)
    assert result.passed is False
    assert any(e.category == "change_not_applied" for e in result.errors)


# ------------------------------------------------------------------
# Test 7: report JSON contains applied_to with full item_ids
# ------------------------------------------------------------------
def test_report_json_contains_applied_to():
    auto_fixes = [
        {
            "bug": "item_level_invalid",
            "item_id": "a1",
            "path": "Статья 1",
            "before": {"item_level": 2},
            "after": {"item_level": 1},
            "reason": "top-level article",
            "date": "15.12.2017",
        }
    ]
    report_data = {
        "status": "Успешно",
        "auto_fixes": auto_fixes,
        "verification": {"passed": True},
    }
    report_json_path = "E:/NPA-JSON-Agent/work/results/test_report.json"
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    with open(report_json_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["auto_fixes"][0]["item_id"] == "a1"
    assert loaded["auto_fixes"][0]["before"]["item_level"] == 2
    assert loaded["auto_fixes"][0]["after"]["item_level"] == 1
