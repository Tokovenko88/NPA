"""Сохранение полной истории документа после внесения изменений.

Модуль фиксирует снимки (snapshot) состояния документа после каждого
применяемого изменения и после финальной перестройки. Это гарантирует,
что:

* исходное состояние целевого НПА всегда доступно для восстановления;
* любое промежуточное изменение можно визуализировать / откатить;
* полная история трансформаций сохраняется в ``learning/history/``.

Каждый снимок — это самостоятельный JSON-файл с метаданными о том,
какое изменение (change_index) и с каким результатом (applied / error)
привело к этому состоянию.
"""

import copy
import hashlib
import json
import os
from datetime import datetime


class DocumentHistory:
    """Управление версиями снимками документа в рамках одного запуска."""

    SNAPSHOTS_SUBDIR = 'history'

    def __init__(self, base_dir, run_id=None, case_id=None, attempt_id=None, iteration_number=None):
        if run_id is None:
            run_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.run_id = run_id
        self.base_dir = os.path.join(base_dir, self.SNAPSHOTS_SUBDIR, run_id)
        os.makedirs(self.base_dir, exist_ok=True)
        self._snapshots = []
        self._counter = 0
        self._source_hash = None
        self._index_path = os.path.join(self.base_dir, '_index.json')
        self.case_id = case_id
        self.attempt_id = attempt_id
        self.iteration_number = iteration_number

    @property
    def index_path(self):
        return self._index_path

    def set_source(self, source_data):
        if source_data is None:
            return
        raw = json.dumps(source_data, ensure_ascii=False, sort_keys=True).encode('utf-8')
        self._source_hash = hashlib.sha256(raw).hexdigest()

    @property
    def source_hash(self):
        return self._source_hash

    def snapshot(self, label, data, metadata=None):
        """Сохранить снимок документа с метаданными.

        Parameters
        ----------
        label : str
            Краткая метка (например, ``before_changes``, ``after_change_3``,
            ``after_rebuild``).
        data : dict
            Состояние документа.
        metadata : dict | None
            Дополнительные сведения (номер изменения, structural_element,
            тип, применено / не применено, сообщение об ошибке и т.п.).
        """
        self._counter += 1
        idx = self._counter
        filename = f"{idx:04d}_{label}.json"
        path = os.path.join(self.base_dir, filename)
        payload = copy.deepcopy(data)
        snapshot = {
            'snapshot_id': idx,
            'label': label,
            'filename': filename,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {},
        }
        self._snapshots.append(snapshot)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self._write_index()
        return snapshot

    def _write_index(self):
        with open(self._index_path, 'w', encoding='utf-8') as f:
            json.dump({
                'run_id': self.run_id,
                'source_hash': self._source_hash,
                'case_id': self.case_id,
                'attempt_id': self.attempt_id,
                'iteration_number': self.iteration_number,
                'snapshots': self._snapshots,
            }, f, ensure_ascii=False, indent=2)

    def finalize_run(self, outcomes, metadata=None):
        """Записать итоговый результат запуска с классификацией исходов.

        Parameters
        ----------
        outcomes : list[dict]
            Список исходов изменения. Каждый элемент должен содержать
            ``structural_element`` и ``outcome`` (``resolved``, ``applied``,
            ``verified_success``, ``failed``, ``verification_failed`` или
            пользовательское значение).
        metadata : dict | None
            Дополнительные метаданные запуска.

        Returns
        -------
        dict
            Финальные метаданные, включая флаги ``trusted_for_positive_learning``
            и ``diagnostic_learning_only``.
        """
        verified_success = any(o.get('outcome') == 'verified_success' for o in outcomes)
        has_failure = any(o.get('outcome') in ('failed', 'verification_failed') for o in outcomes)
        unknown_outcomes = [o for o in outcomes if o.get('outcome') not in (
            'resolved', 'applied', 'verified_success', 'failed', 'verification_failed'
        )]

        trusted = bool(verified_success and not has_failure and not unknown_outcomes)
        diagnostic_only = bool(has_failure or not verified_success or unknown_outcomes)

        final_metadata = {
            'outcomes': outcomes,
            'trusted_for_positive_learning': trusted,
            'diagnostic_learning_only': diagnostic_only,
            'finalized_at': datetime.now().isoformat(),
            'verified_success_count': sum(1 for o in outcomes if o.get('outcome') == 'verified_success'),
            'apply_fail_count': sum(1 for o in outcomes if o.get('outcome') == 'failed'),
            'verification_fail_count': sum(1 for o in outcomes if o.get('outcome') == 'verification_failed'),
        }
        if unknown_outcomes:
            final_metadata['unknown_outcomes'] = unknown_outcomes
        if metadata:
            final_metadata.update(metadata)

        self._write_index()
        return final_metadata

    def list_snapshots(self):
        return list(self._snapshots)

    def load_snapshot(self, snapshot_id):
        match = next((s for s in self._snapshots if s['snapshot_id'] == snapshot_id), None)
        if not match:
            return None
        path = os.path.join(self.base_dir, match['filename'])
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        return None

    def diff(self, from_id, to_id):
        """Краткий diff между двумя снимками: список item_id, чьи revisions изменены."""
        from_doc = self.load_snapshot(from_id)
        to_doc = self.load_snapshot(to_id)
        if from_doc is None or to_doc is None:
            return {'error': 'Snapshot not found'}

        def collect_revs(doc):
            result = {}
            items = []
            def walk(its):
                for it in its:
                    items.append(it)
                    walk(it.get('item_children', []))
            walk(doc.get('npa_items_revision', []))
            for it in items:
                item_id = it.get('item_id')
                revs = it.get('revisions', [])
                if revs:
                    latest = revs[-1]
                    result[item_id] = {
                        'mod_type': latest.get('mod_type'),
                        'modified_by_id': latest.get('modified_by_id'),
                        'valid_from': latest.get('valid_from'),
                        'valid_to': latest.get('valid_to'),
                    }
            return result

        before = collect_revs(from_doc)
        after = collect_revs(to_doc)
        changes = []
        all_ids = list(dict.fromkeys(list(before.keys()) + list(after.keys())))
        for item_id in all_ids:
            b = before.get(item_id, {})
            a = after.get(item_id, {})
            if b != a:
                changes.append({
                    'item_id': item_id,
                    'before': b,
                    'after': a,
                })
        return {'changed_elements': changes, 'count': len(changes)}

    def cleanup(self, keep=None):
        """Удалить отработанные снимки, оставив указанные (или все, если keep=None)."""
        if keep is None:
            keep = set(s['snapshot_id'] for s in self._snapshots)
        for snap in self._snapshots:
            if snap['snapshot_id'] not in keep:
                path = os.path.join(self.base_dir, snap['filename'])
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        self._write_index()
