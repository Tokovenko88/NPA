"""Regression tests for heading-in-body and revision-history bugs."""

import copy

from datetime import datetime

from npa_processor.core.html_parser import NpaToJsonGenerator
from npa_processor.processing.element_ops import (
    _add_new_element,
    _ensure_path,
    _transfer_structural_state,
    rebuild_element_with_history,
    sync_structural_element_recursive,
)
from npa_processor.processing.html_utils import parse_structural_tokens
from npa_processor.learning.learner import LearningEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data():
    return {
        'npa_id': '16012',
        'npa_type': 'law',
        'npa_number': '269-ЗС',
        'npa_items_revision': [],
    }


# ---------------------------------------------------------------------------
# BUG 1: heading must not leak into body
# ---------------------------------------------------------------------------

def test_heading_not_added_to_body_article_with_title():
    html = (
        "<p>Статья 5. Общие положения</p>"
        "<p>Первый абзац.</p>"
    )
    gen = NpaToJsonGenerator(
        html,
        doc_type='law',
        document_id='16012',
        fragment_element_id='16012_article_5',
        root_number='5',
        root_type='article',
    )
    items, _ = gen.generate_toc()
    article = items[0]
    assert article['head_revisions'][0]['head_text'] == 'Общие положения'
    body_texts = [b['html_text'] for b in article.get('revisions', [{}])[0].get('body', [])]
    assert not any('Статья 5' in t for t in body_texts)
    assert body_texts[0] == '<p>Первый абзац.</p>'


def test_heading_not_added_to_body_article_without_title():
    html = (
        "<p>Статья 5</p>"
        "<p>Первый абзац.</p>"
    )
    gen = NpaToJsonGenerator(
        html,
        doc_type='law',
        document_id='16012',
        fragment_element_id='16012_article_5',
        root_number='5',
        root_type='article',
    )
    items, _ = gen.generate_toc()
    article = items[0]
    assert article.get('head_revisions', []) == []
    body_texts = [b['html_text'] for b in article.get('revisions', [{}])[0].get('body', [])]
    assert not any('Статья 5' in t for t in body_texts)
    assert body_texts[0] == '<p>Первый абзац.</p>'


def test_heading_with_leading_quotes_not_in_body():
    data = _make_data()
    data['npa_items_revision'].append({
        'item_id': '16012_article_5',
        'item_type': 'article',
        'item_number': '5',
        'item_level': 1,
        'head_revisions': [],
        'revisions': [],
        'item_children': [],
        '_pending_new_redaction_html': (
            '<p>«Статья 5. Общие положения»</p>'
            '<p>Первый абзац.</p>'
        ),
        '_pending_mod_type': 'add',
        '_pending_valid_from': '15.12.2017',
        '_pending_modified_by_id': '33699',
    })

    ok = rebuild_element_with_history(
        data,
        '16012_article_5',
        datetime(2026, 6, 15),
        '33699',
        doc_type='law',
    )
    assert ok is True
    article = data['npa_items_revision'][0]
    assert article['head_revisions'][0]['head_text'] == 'Общие положения'
    body_texts = [b['html_text'] for b in article['revisions'][0].get('body', [])]
    assert not any('Статья 5' in t for t in body_texts)
    assert body_texts[0] == '<p>Первый абзац.</p>'


# ---------------------------------------------------------------------------
# BUG 2: new element must have exactly one revision after rebuild
# ---------------------------------------------------------------------------

def test_new_element_has_single_revision_after_rebuild():
    data = _make_data()
    data['npa_items_revision'].append({
        'item_id': '16012_article_5',
        'item_type': 'article',
        'item_number': '5',
        'item_level': 1,
        'head_revisions': [],
        'revisions': [],
        'item_children': [],
        '_pending_new_redaction_html': '<p>Статья 5. Заголовок</p><p>Текст.</p>',
        '_pending_mod_type': 'add',
        '_pending_valid_from': '15.12.2017',
        '_pending_modified_by_id': '33699',
    })

    ok = rebuild_element_with_history(
        data,
        '16012_article_5',
        datetime(2026, 6, 15),
        '33699',
        doc_type='law',
    )
    assert ok is True
    article = data['npa_items_revision'][0]
    assert len(article.get('revisions', [])) == 1
    body_texts = [b['html_text'] for b in article['revisions'][0].get('body', [])]
    assert not any('Статья 5' in t for t in body_texts)
    assert article['head_revisions'][0]['head_text'] == 'Заголовок'


def test_existing_element_preserves_revisions_after_rebuild():
    data = _make_data()
    data['npa_items_revision'].append({
        'item_id': '16012_article_5',
        'item_type': 'article',
        'item_number': '5',
        'item_level': 1,
        'head_revisions': [{'head_text': 'Старое название'}],
        'revisions': [
            {
                'body': [{'type': 'paragraph', 'html_text': '<p>Старый текст.</p>', 'order': 1}],
                'valid_from': '01.01.2020',
                'valid_to': '14.12.2017',
            },
            {
                'body': [{'type': 'paragraph', 'html_text': '<p>Новый текст.</p>', 'order': 1}],
                'valid_from': '15.12.2017',
            },
        ],
        'item_children': [],
        '_pending_new_redaction_html': '<p>Статья 5. Новое название</p><p>Обновлённый текст.</p>',
        '_pending_mod_type': 'new_redaction',
        '_pending_valid_from': '15.12.2017',
        '_pending_modified_by_id': '33699',
    })

    ok = rebuild_element_with_history(
        data,
        '16012_article_5',
        datetime(2026, 6, 15),
        '33699',
        doc_type='law',
    )
    assert ok is True
    article = data['npa_items_revision'][0]
    assert len(article.get('revisions', [])) == 3
    assert article['revisions'][0]['body'][0]['html_text'] == '<p>Старый текст.</p>'
    assert article['revisions'][1]['body'][0]['html_text'] == '<p>Новый текст.</p>'
    body_texts = [b['html_text'] for b in article['revisions'][2].get('body', [])]
    assert not any('Статья 5' in t for t in body_texts)
    active_head = next(
        (r['head_text'] for r in reversed(article['head_revisions']) if r.get('valid_to') is None),
        None,
    )
    assert active_head == 'Новое название'


# ---------------------------------------------------------------------------
# BUG 2 continued: structural move must preserve all revisions
# ---------------------------------------------------------------------------

def test_revision_history_preserved_after_structural_move():
    old_child = {
        'item_id': '16012_article_5_part_1',
        'item_type': 'part',
        'item_number': '1',
        'item_level': 2,
        'revisions': [
            {'body': [{'type': 'paragraph', 'html_text': '<p>Старая часть 1.</p>', 'order': 1}], 'valid_from': '01.01.2020'},
            {'body': [{'type': 'paragraph', 'html_text': '<p>Новая часть 1.</p>', 'order': 1}], 'valid_from': '15.12.2017'},
        ],
        'item_children': [],
    }
    new_child = {
        'item_id': '16012_article_5_part_1',
        'item_type': 'part',
        'item_number': '1',
        'item_level': 2,
        'item_children': [],
    }

    _transfer_structural_state(old_child, new_child)

    assert len(new_child.get('revisions', [])) == 2
    assert new_child['revisions'][0]['body'][0]['html_text'] == '<p>Старая часть 1.</p>'
    assert new_child['revisions'][1]['body'][0]['html_text'] == '<p>Новая часть 1.</p>'
    assert old_child['revisions'][0]['body'][0]['html_text'] == '<p>Старая часть 1.</p>'


# ---------------------------------------------------------------------------
# BUG 3: learning must only mark verified_success after verification
# ---------------------------------------------------------------------------

def test_learning_verified_success_requires_verification():
    import os
    from npa_processor.paths import LEARNING_DIR
    mapping_path = os.path.join(LEARNING_DIR, 'element_mappings.json')
    if os.path.exists(mapping_path):
        os.remove(mapping_path)
    engine = LearningEngine()
    engine.record_mapping(
        'Статья 5',
        '16012_article_5',
        success=True,
        target_npa_id='16012',
        source_npa_id='33699',
        change_type='new_redaction',
        source_context='33699',
    )
    rec = engine._mappings[engine._mapping_key('Статья 5', '16012', '33699', 'new_redaction')]
    assert rec['verified_success_count'] == 1
    assert rec['apply_fail_count'] == 0
    assert rec['verification_fail_count'] == 0
