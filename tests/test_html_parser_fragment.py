"""Regression tests for fragment HTML parsing and rebuild."""

from datetime import datetime

from npa_processor.core.html_parser import NpaToJsonGenerator
from npa_processor.processing.element_ops import rebuild_element_with_history


def test_fragment_parse_article_root():
    html = "<p>1. Первая часть текста.</p><p>2. Вторая часть текста.</p>"
    gen = NpaToJsonGenerator(html, fragment_element_id='toc_article_1')
    items, _ = gen.generate_toc()
    assert len(items) == 1
    article = items[0]
    assert article['item_type'] == 'article'
    assert article['item_number'] == '1'
    assert 'item_children' in article
    assert len(article['item_children']) == 1
    assert article['item_children'][0]['item_type'] == 'part'
    assert article['item_children'][0]['item_number'] == '2'


def test_fragment_parse_part_root():
    html = "<p>1) Первый пункт.</p><p>2) Второй пункт.</p>"
    gen = NpaToJsonGenerator(html, fragment_element_id='toc_article_1_part_1')
    items, _ = gen.generate_toc()
    assert len(items) == 1
    part = items[0]
    assert part['item_type'] == 'part'
    assert part['item_number'] == '1'
    assert 'item_children' in part
    assert len(part['item_children']) == 1
    assert part['item_children'][0]['item_type'] == 'part'
    assert part['item_children'][0]['item_number'] == '2)'


def test_fragment_parse_nested_enumeration():
    html = "<p>а) Первый подпункт.</p><p>б) Второй подпункт.</p>"
    gen = NpaToJsonGenerator(html, fragment_element_id='toc_article_1_part_1_point_1')
    items, _ = gen.generate_toc()
    assert len(items) == 1
    point = items[0]
    assert point['item_type'] == 'point'
    assert point['item_number'] == '1'
    assert 'item_children' in point
    assert len(point['item_children']) == 2
    assert point['item_children'][0]['item_type'] == 'subpoint'
    assert point['item_children'][0]['item_number'] == 'а)'
    assert point['item_children'][1]['item_type'] == 'subpoint'
    assert point['item_children'][1]['item_number'] == 'б)'


def test_fragment_parse_structured_table():
    html = (
        "<table border='1'>"
        "<tr><td>1.</td><td>Первая строка</td></tr>"
        "<tr><td>2.</td><td>Вторая строка</td></tr>"
        "</table>"
    )
    gen = NpaToJsonGenerator(html, fragment_element_id='toc_structured_table_1')
    items, _ = gen.generate_toc()
    assert len(items) == 1
    table = items[0]
    assert table['item_type'] == 'structured_table'
    assert 'item_children' in table
    assert len(table['item_children']) == 2
    assert table['item_children'][0]['item_type'] == 'point'
    assert table['item_children'][0]['item_number'] == '1'
    assert table['item_children'][1]['item_type'] == 'point'
    assert table['item_children'][1]['item_number'] == '2'


def test_rebuild_element_with_history_preserves_structure():
    data = {
        'npa_items_revision': [
                {
                    'item_id': 'toc_article_1',
                    'item_type': 'article',
                    'item_number': '1',
                    'item_level': 1,
                '_pending_new_redaction_html': "<p>1. Новая часть 1.</p><p>2. Новая часть 2.</p>",
                'revisions': [
                    {
                        'body': [
                            {'type': 'paragraph', 'html_text': '<p>Старая версия статьи 1.</p>', 'order': 1}
                        ],
                        'valid_from': '01.01.2020',
                    }
                ],
                    'item_children': [
                        {
                            'item_id': 'toc_article_1_part_1',
                            'item_type': 'part',
                            'item_number': '1',
                            'item_level': 2,
                        'revisions': [
                            {
                                'body': [
                                    {'type': 'paragraph', 'html_text': '<p>Старая часть 1.</p>', 'order': 1}
                                ],
                                'valid_from': '01.01.2020',
                            }
                        ],
                        'item_children': [],
                    }
                ],
            }
        ]
    }
    result = rebuild_element_with_history(
        data,
        'toc_article_1',
        datetime(2026, 6, 15),
        'user_1',
        doc_type='law',
    )
    assert result is True
    article = data['npa_items_revision'][0]
    assert 'item_children' in article
    assert len(article['item_children']) == 2
    assert article['item_children'][0]['item_number'] == '1'
    assert article['item_children'][1]['item_number'] == '2'
