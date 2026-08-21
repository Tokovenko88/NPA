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


def test_new_redaction_must_not_inherit_child_refs():
    data = {
        "npa_items_revision": [
            {
                "item_id": "article_2",
                "item_type": "article",
                "item_number": "2",
                "item_level": 1,
                "revisions": [
                    {
                        "body": [
                            {"type": "child_ref", "item_id": "part_1", "order": 1},
                            {"type": "child_ref", "item_id": "part_2", "order": 2},
                        ],
                        "valid_from": "08.08.2016",
                        "valid_to": "14.12.2017",
                    },
                    {
                        "body": [
                            {"type": "paragraph", "html_text": "<p>New text only</p>", "order": 1},
                            {"type": "child_ref", "item_id": "part_1", "order": 2},
                            {"type": "child_ref", "item_id": "part_2", "order": 3},
                        ],
                        "mod_type": "new_redaction",
                        "modified_by_id": "source_article_1",
                        "valid_from": "15.12.2017",
                    },
                ],
                "item_children": [
                    {
                        "item_id": "part_1",
                        "item_type": "part",
                        "item_number": "1",
                        "item_level": 2,
                        "revisions": [
                            {
                                "body": [{"type": "paragraph", "html_text": "<p>Old part 1</p>", "order": 1}],
                                "valid_to": "14.12.2017",
                                "not_valid": "source_article_1",
                                "valid_from": "08.08.2016",
                            }
                        ],
                    },
                    {
                        "item_id": "part_2",
                        "item_type": "part",
                        "item_number": "2",
                        "item_level": 2,
                        "revisions": [
                            {
                                "body": [{"type": "paragraph", "html_text": "<p>Old part 2</p>", "order": 1}],
                                "valid_to": "14.12.2017",
                                "not_valid": "source_article_1",
                                "valid_from": "08.08.2016",
                            }
                        ],
                    },
                ],
            }
        ]
    }
    verifier = StructureVerifier()
    result = verifier.verify(data)
    assert result.passed is False
    assert any(e.category == "revision_body_source_violation" for e in result.errors)


def test_new_redaction_without_inherited_child_refs_passes():
    data = {
        "npa_items_revision": [
            {
                "item_id": "article_2",
                "item_type": "article",
                "item_number": "2",
                "item_level": 1,
                "revisions": [
                    {
                        "body": [
                            {"type": "child_ref", "item_id": "part_1", "order": 1},
                            {"type": "child_ref", "item_id": "part_2", "order": 2},
                        ],
                        "valid_from": "08.08.2016",
                        "valid_to": "14.12.2017",
                    },
                    {
                        "body": [
                            {"type": "paragraph", "html_text": "<p>New text only</p>", "order": 1},
                        ],
                        "mod_type": "new_redaction",
                        "modified_by_id": "source_article_1",
                        "valid_from": "15.12.2017",
                    },
                ],
                "item_children": [
                    {
                        "item_id": "part_1",
                        "item_type": "part",
                        "item_number": "1",
                        "item_level": 2,
                        "revisions": [
                            {
                                "body": [{"type": "paragraph", "html_text": "<p>Old part 1</p>", "order": 1}],
                                "valid_to": "14.12.2017",
                                "not_valid": "source_article_1",
                                "valid_from": "08.08.2016",
                            }
                        ],
                    },
                    {
                        "item_id": "part_2",
                        "item_type": "part",
                        "item_number": "2",
                        "item_level": 2,
                        "revisions": [
                            {
                                "body": [{"type": "paragraph", "html_text": "<p>Old part 2</p>", "order": 1}],
                                "valid_to": "14.12.2017",
                                "not_valid": "source_article_1",
                                "valid_from": "08.08.2016",
                            }
                        ],
                    },
                ],
            }
        ]
    }
    verifier = StructureVerifier()
    result = verifier.verify(data)
    assert result.passed is True
    assert not any(e.category == "revision_body_source_violation" for e in result.errors)


def test_article_2_regression_new_redaction_without_parts():
    data = {
        "npa_items_revision": [
            {
                "item_id": "16012_article_2",
                "item_type": "article",
                "item_number": "2",
                "item_level": 1,
                "revisions": [
                    {
                        "body": [
                            {"type": "child_ref", "item_id": "16012_article_2_part_1", "order": 1},
                            {"type": "child_ref", "item_id": "16012_article_2_part_2", "order": 2},
                        ],
                        "valid_from": "08.08.2016",
                        "valid_to": "14.12.2017",
                    },
                    {
                        "body": [
                            {"type": "paragraph", "html_text": "<p class=\"justifyfull\">В собственность бесплатно отдельным категориям граждан могут быть предоставлены однократно земельные участки с видом разрешенного пользования «для индивидуального жилищного строительства».</p>", "order": 1},
                        ],
                        "mod_type": "new_redaction",
                        "modified_by_id": "33699_article_1_point_3",
                        "valid_from": "15.12.2017",
                    },
                ],
                "head_revisions": [
                    {"head_text": "Цели предоставления земельного участка гражданам в собственность бесплатно", "valid_to": "14.12.2017"},
                    {"head_text": "Вид разрешенного использования предоставляемого земельного участка в собственность бесплатно"},
                ],
                "item_children": [
                    {
                        "item_id": "16012_article_2_part_1",
                        "item_type": "part",
                        "item_number": "1",
                        "item_level": 2,
                        "revisions": [
                            {
                                "body": [
                                    {"type": "paragraph", "html_text": "<p>Old part 1</p>", "order": 1},
                                ],
                                "valid_to": "14.12.2017",
                                "not_valid": "33699_article_1_point_3",
                                "valid_from": "08.08.2016",
                            }
                        ],
                    },
                    {
                        "item_id": "16012_article_2_part_2",
                        "item_type": "part",
                        "item_number": "2",
                        "item_level": 2,
                        "revisions": [
                            {
                                "body": [
                                    {"type": "paragraph", "html_text": "<p>Old part 2</p>", "order": 1},
                                ],
                                "valid_to": "14.12.2017",
                                "not_valid": "33699_article_1_point_3",
                                "valid_from": "08.08.2016",
                            }
                        ],
                    },
                ],
            }
        ]
    }
    verifier = StructureVerifier()
    result = verifier.verify(data)
    assert result.passed is True
    new_rev = data["npa_items_revision"][0]["revisions"][-1]
    assert new_rev["mod_type"] == "new_redaction"
    assert len(new_rev["body"]) == 1
    assert new_rev["body"][0]["type"] == "paragraph"
    child_refs = [b for b in new_rev["body"] if b.get("type") == "child_ref"]
    assert child_refs == []


def test_invariant_no_two_active_revisions():
    data = {
        "npa_items_revision": [
            {
                "item_id": "article_1",
                "item_type": "article",
                "item_number": "1",
                "item_level": 1,
                "revisions": [
                    {"body": [{"type": "paragraph", "html_text": "<p>Old</p>", "order": 1}], "valid_from": "01.01.2020", "valid_to": None},
                    {"body": [{"type": "paragraph", "html_text": "<p>New</p>", "order": 1}], "mod_type": "new_redaction", "valid_from": "15.01.2020", "valid_to": None},
                ],
            }
        ]
    }
    verifier = StructureVerifier()
    result = verifier.verify(data)
    assert result.passed is False
    assert any(e.category == "revision_active_conflict" for e in result.errors)


def test_invariant_child_ref_removal_does_not_delete_child():
    data = {
        "npa_items_revision": [
            {
                "item_id": "article_1",
                "item_type": "article",
                "item_number": "1",
                "item_level": 1,
                "revisions": [
                    {
                        "body": [
                            {"type": "child_ref", "item_id": "point_1", "order": 1},
                        ],
                        "valid_from": "01.01.2020",
                        "valid_to": "14.01.2020",
                    },
                    {
                        "body": [],
                        "mod_type": "new_redaction",
                        "valid_from": "15.01.2020",
                    },
                ],
                "item_children": [
                    {
                        "item_id": "point_1",
                        "item_type": "point",
                        "item_number": "1",
                        "item_level": 2,
                        "revisions": [
                            {"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "valid_from": "01.01.2020"},
                        ],
                    }
                ],
            }
        ]
    }
    verifier = StructureVerifier()
    result = verifier.verify(data)
    assert result.passed is True
    child = data["npa_items_revision"][0]["item_children"][0]
    assert child["item_id"] == "point_1"
    assert len(child.get("revisions", [])) == 1


def test_invariant_modified_by_id_is_full_item_id():
    data = {
        "npa_items_revision": [
            {
                "item_id": "article_1",
                "item_type": "article",
                "item_number": "1",
                "item_level": 1,
                "revisions": [
                    {"body": [{"type": "paragraph", "html_text": "<p>Text</p>", "order": 1}], "mod_type": "new_redaction", "modified_by_id": "33699", "valid_from": "15.01.2020"},
                ],
            }
        ]
    }
    verifier = StructureVerifier()
    result = verifier.verify(data, source_data={"npa_id": "33699"})
    assert result.passed is False
    assert any(e.category == "modified_by_id_bare" for e in result.errors)
