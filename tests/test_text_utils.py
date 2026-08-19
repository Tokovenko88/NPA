import unittest
from datetime import date

from npa_processor.processing.html_utils import create_element_skeleton
from npa_processor.processing.text_utils import close_revision_date, strip_thinking_tags


class TestTextUtils(unittest.TestCase):
    def test_close_revision_date(self):
        self.assertEqual(close_revision_date(date(2024, 1, 15)), '14.01.2024')
        self.assertEqual(close_revision_date('15.01.2024'), '14.01.2024')
        self.assertEqual(close_revision_date(date(2024, 3, 1)), '29.02.2024')

    def test_strip_thinking_tags(self):
        self.assertEqual(
            strip_thinking_tags('before <thinking>secret</thinking> after'),
            'before after'
        )
        self.assertEqual(
            strip_thinking_tags('```json\n{"html": "<p>x</p>"}\n```'),
            '{"html": "<p>x</p>"}'
        )
        self.assertEqual(
            strip_thinking_tags('```\nplain text\n```'),
            'plain text'
        )

    def test_create_element_skeleton_collision(self):
        existing = {'a1', 'a2'}
        counter = [3]
        s1 = create_element_skeleton(
            item_type='point',
            item_number='1',
            html_text='<p>first</p>',
            parent_id='a1',
            existing_ids=existing,
            id_counter=counter,
            item_level=2,
        )
        s2 = create_element_skeleton(
            item_type='point',
            item_number='1',
            html_text='<p>second</p>',
            parent_id='a1',
            existing_ids=existing,
            id_counter=counter,
            item_level=2,
        )
        self.assertEqual(s1['item_id'], 'a1_point_1')
        self.assertEqual(s2['item_id'], 'a1_point_1_2')
        self.assertEqual(len(existing), 4)


if __name__ == '__main__':
    unittest.main()
