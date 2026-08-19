import unittest
from npa_processor.processing.text_utils import normalize_item_number
from npa_processor.processing.tree_utils import find_item_by_id


class TestNormalizeAndFind(unittest.TestCase):
    def test_normalize_item_number_point(self):
        self.assertEqual(normalize_item_number('point', '1'), '1)')
        self.assertEqual(normalize_item_number('point', '1)'), '1)')
        self.assertEqual(normalize_item_number('point', ''), '')

    def test_normalize_item_number_article(self):
        self.assertEqual(normalize_item_number('article', '5'), '5')
        self.assertEqual(normalize_item_number('article', '5.1'), '5.1')

    def test_find_item_by_id(self):
        data = {'npa_items_revision': [
            {'item_id': 'a1', 'item_children': [{'item_id': 'a1.1', 'item_children': []}]}
        ]}
        self.assertEqual(find_item_by_id(data, 'a1.1')['item_id'], 'a1.1')
        self.assertEqual(find_item_by_id(data, 'a1')['item_id'], 'a1')
        self.assertIsNone(find_item_by_id(data, 'missing'))


if __name__ == '__main__':
    unittest.main()
