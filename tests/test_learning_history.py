import json
import os

import pytest

from npa_processor.learning.history import DocumentHistory


@pytest.fixture
def tmp_learning_dir(tmp_path, monkeypatch):
    learning_dir = tmp_path / 'learning'
    learning_dir.mkdir()
    monkeypatch.setattr('npa_processor.paths.LEARNING_DIR', str(learning_dir))
    monkeypatch.setattr('npa_processor.learning.learner.LEARNING_DIR', str(learning_dir))
    base = str(learning_dir)
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.LOG_FILE', os.path.join(base, 'learning_log.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.MAPPINGS_FILE', os.path.join(base, 'element_mappings.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.PROMPT_FEEDBACK_FILE', os.path.join(base, 'prompt_feedback.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.VERIFICATION_LOG_FILE', os.path.join(base, 'verification_log.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.CHANGE_OUTCOMES_FILE', os.path.join(base, 'change_outcomes.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.RECOVERY_LOG_FILE', os.path.join(base, 'recovery_log.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.RUN_LOG_FILE', os.path.join(base, 'run_log.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.ERROR_EXAMPLES_FILE', os.path.join(base, 'error_examples.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.BUG_FIXES_FILE', os.path.join(base, 'bug_fixes.json'))
    monkeypatch.setattr('npa_processor.learning.learner.LearningEngine.SEED_EXAMPLES_FILE', os.path.join(base, 'seed_examples.json'))
    return str(learning_dir)


def test_history_index_records_case_attempt_metadata(tmp_path):
    dh = DocumentHistory(
        str(tmp_path),
        run_id='run_1',
        case_id='case_1',
        attempt_id='att_1',
        iteration_number=3,
    )
    dh.set_source({'npa_id': 'test'})
    dh.snapshot('test', {'npa_items_revision': []})

    with open(dh.index_path, encoding='utf-8') as f:
        idx = json.load(f)
    assert idx['case_id'] == 'case_1'
    assert idx['attempt_id'] == 'att_1'
    assert idx['iteration_number'] == 3
    assert idx['run_id'] == 'run_1'


def test_unknown_outcome_is_diagnostic_only(tmp_path):
    dh = DocumentHistory(str(tmp_path), run_id='run_unknown')
    outcomes = [
        {'structural_element': 'статья 1', 'outcome': 'verified_success'},
        {'structural_element': 'статья 2', 'outcome': 'custom_unknown'},
    ]
    result = dh.finalize_run(outcomes)
    assert result['diagnostic_learning_only'] is True
    assert result['trusted_for_positive_learning'] is False
    assert len(result.get('unknown_outcomes', [])) == 1


def test_mapping_context_prevents_cross_npa_reuse(tmp_learning_dir):
    from npa_processor.learning.learner import LearningEngine

    engine = LearningEngine()
    engine.record_mapping(
        'статья 1', 'item_a', success=True,
        target_npa_id='npa_a', source_npa_id='npa_x', change_type='new_redaction',
    )
    result_a = engine.get_reliable_mapping(
        'статья 1', target_npa_id='npa_a', source_npa_id='npa_x', change_type='new_redaction',
    )
    assert result_a == 'item_a'

    result_b = engine.get_reliable_mapping(
        'статья 1', target_npa_id='npa_b', source_npa_id='npa_x', change_type='new_redaction',
    )
    assert result_b is None


def test_resolved_mapping_does_not_increase_verified_confidence(tmp_learning_dir):
    from npa_processor.learning.learner import LearningEngine

    engine = LearningEngine()
    engine.record_mapping(
        'статья 1', 'item_1', success=False,
        target_npa_id='npa_a', outcome='resolved',
    )
    diag = engine.get_mapping_diagnostics('статья 1', target_npa_id='npa_a')
    assert diag['verified_success_count'] == 0
    assert diag['telemetry_count'] == 1
    assert diag['confidence'] == pytest.approx(0.0 / (0.0 + 0.0 + 0.0 + 2))


def test_repeated_failures_in_one_case_are_deduplicated_for_global_confidence(tmp_learning_dir):
    from npa_processor.learning.learner import LearningEngine

    engine = LearningEngine()
    for _ in range(10):
        engine.record_mapping(
            'статья 1', 'item_1', success=False,
            target_npa_id='npa_a', case_id='case_same',
        )
    engine.record_mapping(
        'статья 1', 'item_1', success=True,
        target_npa_id='npa_a', case_id='case_same',
    )
    diag = engine.get_mapping_diagnostics('статья 1', target_npa_id='npa_a')
    assert diag['case_ids'] == ['case_same']
    assert diag['contested'] is True
    assert diag['verified_success_count'] == 1
    assert diag['apply_fail_count'] == 10
