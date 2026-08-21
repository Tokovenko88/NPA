"""Построение истории ревизий."""


from npa_processor.processing.tree_utils import insert_child_ref_in_body


def extract_child_refs_from_revision(rev):
    if not rev:
        return []
    return [b for b in rev.get('body', []) if b.get('type') == 'child_ref']

def sync_parent_body_with_children(parent_item, log_callback=None, allow_new_redaction=False):
    if not parent_item:
        return
    children = parent_item.get('item_children', [])
    if not children:
        return
    revisions = parent_item.get('revisions', [])
    active_rev = None
    for rev in reversed(revisions):
        if rev.get('valid_to') is None:
            active_rev = rev
            break
    if not active_rev and revisions:
        active_rev = revisions[-1]
    if not active_rev:
        if log_callback:
            log_callback(f"  sync_parent_body_with_children: нет активной ревизии у {parent_item.get('item_id')}", 'warning')
        return
    if not allow_new_redaction and active_rev.get('mod_type') == 'new_redaction':
        if log_callback:
            log_callback(f"  sync_parent_body_with_children: пропуск new_redaction у {parent_item.get('item_id')}", 'info')
        return
    body = active_rev.get('body', [])
    child_refs = [b for b in body if b.get('type') == 'child_ref']
    for child in children:
        if not any(ref.get('item_id') == child.get('item_id') for ref in child_refs):
            insert_child_ref_in_body(parent_item, child.get('item_id'), log_callback)

def remove_empty_children(data):
    def remove_empty(item):
        if 'item_children' in item and isinstance(item['item_children'], list):
            item['item_children'] = [c for c in item['item_children'] if c is not None]
            for child in item['item_children']:
                remove_empty(child)
        item.pop('_precreated_placeholder', None)
        item.pop('_pending_new_redaction_html', None)
        item.pop('_pending_html', None)
        item.pop('_pending_mod_type', None)
        item.pop('_pending_modified_by_id', None)
        item.pop('_pending_valid_from', None)
        item.pop('_pending_highlights', None)
    if 'npa_items_revision' in data:
        for item in data['npa_items_revision']:
            remove_empty(item)
