"""Smoke-тест импортов ядра пайплайна (P3)."""

import unittest


class TestCoreImports(unittest.TestCase):
    def test_core_imports(self):
        from npa_processor.processing.change_applier import apply_change, apply_stage1_revocation, apply_stage2_date_change
        from npa_processor.processing.element_ops import rebuild_element_with_history
        from npa_processor.processing.recovery import attempt_recover_change
        from npa_processor.processing.reorganization import detect_and_apply_structural_reorganization
        self.assertTrue(callable(apply_change))
        self.assertTrue(callable(apply_stage1_revocation))
        self.assertTrue(callable(apply_stage2_date_change))
        self.assertTrue(callable(rebuild_element_with_history))
        self.assertTrue(callable(attempt_recover_change))
        self.assertTrue(callable(detect_and_apply_structural_reorganization))

    def test_recovery_module_public_name(self):
        import npa_processor.processing.recovery as recovery
        self.assertTrue(hasattr(recovery, 'attempt_recover_change'))
        self.assertFalse(hasattr(recovery, '_attempt_recover_change'))


if __name__ == '__main__':
    unittest.main()
