"""Проверка сигнатуры и basic-поведения attempt_recover_change (P0-1 / P2-1)."""

import inspect
import unittest
from datetime import date

from npa_processor.processing import recovery
from npa_processor.processing.recovery import attempt_recover_change


class _ReliableLearner:
    """Mock learning-движка, который всегда предлагает надёжный item_id."""

    def get_suggestions_for_element(self, structural):
        return []

    def get_reliable_mapping(self, structural):
        return 'reliable_id_1'


class _NoopLearner:
    def get_suggestions_for_element(self, structural):
        return []

    def get_reliable_mapping(self, structural):
        return None


class TestRecoverySignature(unittest.TestCase):
    def test_signature_has_doc_type(self):
        params = inspect.signature(attempt_recover_change).parameters
        self.assertIn('doc_type', params)
        self.assertEqual(params['doc_type'].default, 'law')

    def test_early_return_no_name_error(self):
        # При отсутствии подсказок/маппингов не должно быть обращения к doc_type.
        change = {'structural_element': 'статья 1', 'type': 'change'}
        result_data = {'npa_items_revision': []}
        ok = attempt_recover_change(
            change, result_data, {'npa_items_revision': []}, date(2024, 1, 15),
            'sid', [], lambda *a, **k: None, _NoopLearner(), {}, doc_type='law',
        )
        self.assertFalse(ok)

    def test_doc_type_propagated_to_apply_change(self):
        captured = {}

        def fake_apply_change(**kw):
            captured['doc_type'] = kw.get('doc_type')
            return True

        def fake_find_target(*a, **k):
            return {'item_id': 'src_1'}

        orig_apply = recovery.apply_change
        orig_find = recovery._find_target_element
        recovery.apply_change = fake_apply_change
        recovery._find_target_element = fake_find_target
        try:
            change = {'structural_element': 'статья 1', 'type': 'change'}
            result_data = {'npa_items_revision': [{'item_id': 't1', 'item_type': 'article', 'item_number': '1'}]}
            ok = attempt_recover_change(
                change, result_data, {'npa_items_revision': []}, date(2024, 1, 15),
                'sid', [], lambda *a, **k: None, _ReliableLearner(), {}, doc_type='law',
            )
            self.assertTrue(ok)
            self.assertEqual(captured.get('doc_type'), 'law')
        finally:
            recovery.apply_change = orig_apply
            recovery._find_target_element = orig_find


if __name__ == '__main__':
    unittest.main()
