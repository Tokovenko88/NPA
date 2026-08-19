"""Тесты единого правила match_item_type_and_number (P1-4)."""

import unittest

from npa_processor.processing.tree_utils import match_item_type_and_number


def _item(i_type, i_number):
    return {'item_type': i_type, 'item_number': i_number}


class TestMatchItemTypeAndNumber(unittest.TestCase):
    def test_exact_and_parens(self):
        self.assertTrue(match_item_type_and_number(_item('point', '1)'), 'point', '1'))
        self.assertTrue(match_item_type_and_number(_item('point', '1'), 'point', '1)'))
        self.assertTrue(match_item_type_and_number(_item('point', '1.'), 'point', '1'))

    def test_roman(self):
        # clean_number превращает римские в арабские
        self.assertTrue(match_item_type_and_number(_item('part', 'II'), 'part', '2'))
        self.assertTrue(match_item_type_and_number(_item('part', '2'), 'part', 'II'))

    def test_superscript(self):
        self.assertTrue(match_item_type_and_number(_item('point', '1²'), 'point', '1²'))

    def test_empty_number_semantics(self):
        # для обычных типов без номера подходит только элемент без номера
        self.assertTrue(match_item_type_and_number(_item('part', ''), 'part', None))
        self.assertFalse(match_item_type_and_number(_item('part', '5'), 'part', None))

    def test_special_types_any_number(self):
        self.assertTrue(match_item_type_and_number(_item('appendix', ''), 'appendix', None))
        self.assertTrue(match_item_type_and_number(_item('appendix', '5'), 'appendix', None))
        self.assertTrue(match_item_type_and_number(_item('preamble', ''), 'preamble', None))
        self.assertTrue(match_item_type_and_number(_item('structured_table', ''), 'structured_table', None))

    def test_type_mismatch(self):
        self.assertFalse(match_item_type_and_number(_item('article', '5'), 'part', '5'))
        self.assertFalse(match_item_type_and_number(None, 'part', '1'))


if __name__ == '__main__':
    unittest.main()
