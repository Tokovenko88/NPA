import sys

import pytest

from npa_processor.learning.verifier import StructureVerifier
from npa_processor.processing.identity import are_structural_elements_identical


def _make_element(item_id, item_type, item_number, body=None, children=None, revisions=None, head_revisions=None, item_level=1):
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
    return element


def _active_revision(element):
    for rev in reversed(element.get("revisions", [])):
        if rev.get("valid_to") is None:
            return rev
    return None


def test_identical_elements_are_identical():
    old = _make_element(
        "old_1", "point", "1",
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_to": None}],
    )
    new = _make_element(
        "new_1", "point", "1",
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_to": None}],
    )
    assert are_structural_elements_identical(old, new) is True


def test_different_body_not_identical():
    old = _make_element(
        "old_1", "point", "1",
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Old</p>", "order": 1}], "valid_to": None}],
    )
    new = _make_element(
        "new_1", "point", "1",
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>New</p>", "order": 1}], "valid_to": None}],
    )
    assert are_structural_elements_identical(old, new) is False


def test_different_number_not_identical():
    old = _make_element(
        "old_1", "point", "1",
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_to": None}],
    )
    new = _make_element(
        "new_1", "point", "2",
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_to": None}],
    )
    assert are_structural_elements_identical(old, new) is False


def test_different_type_not_identical():
    old = _make_element(
        "old_1", "point", "1",
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_to": None}],
    )
    new = _make_element(
        "new_1", "part", "1",
        revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_to": None}],
    )
    assert are_structural_elements_identical(old, new) is False


def test_child_ref_integrity_valid():
    data = {
        "npa_items_revision": [
            _make_element("article_1", "article", "1", children=[
                _make_element("point_1", "point", "1", item_level=2, revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_from": "01.01.2020", "valid_to": None}]),
            ]),
        ]
    }
    data["npa_items_revision"][0]["revisions"] = [{"body": [{"type": "child_ref", "item_id": "point_1", "order": 1}], "valid_from": "01.01.2020", "valid_to": None}]
    verifier = StructureVerifier()
    result = verifier.verify(data)
    assert result.passed is True


def test_child_ref_integrity_broken():
    data = {
        "npa_items_revision": [
            _make_element("article_1", "article", "1", children=[
                _make_element("point_1", "point", "1", revisions=[{"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_to": None}]),
            ]),
        ]
    }
    data["npa_items_revision"][0]["revisions"] = [{"body": [{"type": "child_ref", "item_id": "missing", "order": 1}], "valid_to": None}]
    verifier = StructureVerifier()
    result = verifier.verify(data)
    assert result.passed is False
    assert any(e.category == "child_ref_broken" for e in result.errors)


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason="Windows pytest assertion rewrite corrupts non-ASCII literals in this test file",
)
def test_utf8_report_roundtrip():
    text = "ссылается на несуществующий item_id"
    data = {"npa_items_revision": [{"item_id": "a", "item_type": "article", "item_number": "1", "item_level": 1, "revisions": [{"body": [{"type": "child_ref", "item_id": "missing"}]}], "item_children": []}]}
    verifier = StructureVerifier()
    result = verifier.verify(data)
    msgs = [e.message for e in result.errors]
    found = False
    for m in msgs:
        if text in m:
            found = True
            break
    assert found
