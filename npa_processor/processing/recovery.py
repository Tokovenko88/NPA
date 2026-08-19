"""Recovery of failed changes based on learning history.

Provides ``attempt_recover_change``: re-resolves a failed change's structural
element using proven mappings / suggestions from the learning engine and
retries ``apply_change``.
"""

from npa_processor.processing.change_applier import apply_change
from npa_processor.processing.element_ops import _find_existing_element_flexible
from npa_processor.processing.tree_utils import _find_target_element


def attempt_recover_change(change, result_data, source, valid_from_dt, source_item_id,
                           rebuild_ids, log_callback,
                           learner, change_log_entry, doc_type='law'):
    """Попытаться восстановить проваленное изменение на основе истории самообучения.

    Использует проверенные маппинги и рекомендации по рекавери для переопределения
    resolution структурного элемента.
    """
    structural = change.get('structural_element', '').strip()
    suggestions = learner.get_suggestions_for_element(structural)
    reliable_id = learner.get_reliable_mapping(structural)
    recovered = False
    if reliable_id and reliable_id != change.get('_resolved_item_id'):
        log_callback(f"  RECOVERY: используем проверенный item_id '{reliable_id}' для '{structural}'", 'info')
        change['_resolved_item_id'] = reliable_id
        recovered = True
    else:
        for sug in suggestions:
            log_callback(f"  RECOVERY: согласно истории, для '{structural}' [{sug['category']}] "
                         f"предлагается: {sug['suggestion'][:120]}", 'info')
        if suggestions:
            target_elem = None
            try:
                target_elem = _find_existing_element_flexible(result_data, structural, log_callback)
            except ValueError:
                target_elem = None
            if target_elem:
                change['_resolved_item_id'] = target_elem['item_id']
                recovered = True
    if recovered:
        try:
            ok = apply_change(
                change=change, data=result_data, change_data=source, law_ref=None,
                general_valid_from=valid_from_dt, log_callback=log_callback,
                source_item_id=source_item_id,
                rebuild_ids=rebuild_ids, doc_type=doc_type, extra_options=None,

                source_context_root=_find_target_element(source, result_data, log_callback, doc_type)
                if result_data.get('npa_items_revision') else source,
                ambiguous_callback=None,
            )
            return ok
        except Exception as e:
            log_callback(f"  RECOVERY: исключение при повторном применении: {e}", 'error')
            return False
    return False
