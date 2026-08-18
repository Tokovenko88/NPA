"""РЎРѕС…СЂР°РЅРµРЅРёРµ РїРѕР»РЅРѕР№ РёСЃС‚РѕСЂРёРё РґРѕРєСѓРјРµРЅС‚Р° РїРѕСЃР»Рµ РІРЅРµСЃРµРЅРёСЏ РёР·РјРµРЅРµРЅРёР№.

РњРѕРґСѓР»СЊ С„РёРєСЃРёСЂСѓРµС‚ СЃРЅРёРјРєРё (snapshot) СЃРѕСЃС‚РѕСЏРЅРёСЏ РґРѕРєСѓРјРµРЅС‚Р° РїРѕСЃР»Рµ РєР°Р¶РґРѕРіРѕ
РїСЂРёРјРµРЅСЏРµРјРѕРіРѕ РёР·РјРµРЅРµРЅРёСЏ Рё РїРѕСЃР»Рµ С„РёРЅР°Р»СЊРЅРѕР№ РїРµСЂРµСЃС‚СЂРѕР№РєРё. Р­С‚Рѕ РіР°СЂР°РЅС‚РёСЂСѓРµС‚,
С‡С‚Рѕ:

* РёСЃС…РѕРґРЅРѕРµ СЃРѕСЃС‚РѕСЏРЅРёРµ С†РµР»РµРІРѕРіРѕ РќРџРђ РІСЃРµРіРґР° РґРѕСЃС‚СѓРїРЅРѕ РґР»СЏ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ;
* Р»СЋР±РѕРµ РїСЂРѕРјРµР¶СѓС‚РѕС‡РЅРѕРµ РёР·РјРµРЅРµРЅРёРµ РјРѕР¶РЅРѕ РІРёР·СѓР°Р»РёР·РёСЂРѕРІР°С‚СЊ / РѕС‚РєР°С‚РёС‚СЊ;
* РїРѕР»РЅР°СЏ РёСЃС‚РѕСЂРёСЏ С‚СЂР°РЅСЃС„РѕСЂРјР°С†РёР№ СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ РІ ``07_learning/history/``.

РљР°Р¶РґС‹Р№ СЃРЅРёРјРѕРє вЂ” СЌС‚Рѕ СЃР°РјРѕСЃС‚РѕСЏС‚РµР»СЊРЅС‹Р№ JSON-С„Р°Р№Р» СЃ РјРµС‚Р°РґР°РЅРЅС‹РјРё Рѕ С‚РѕРј,
РєР°РєРѕРµ РёР·РјРµРЅРµРЅРёРµ (change_index) Рё СЃ РєР°РєРёРј СЂРµР·СѓР»СЊС‚Р°С‚РѕРј (applied / error)
РїСЂРёРІРµР»Рѕ Рє СЌС‚РѕРјСѓ СЃРѕСЃС‚РѕСЏРЅРёСЋ.
"""

import os
import json
import copy
import hashlib
from datetime import datetime


class DocumentHistory:
    """РЈРїСЂР°РІР»РµРЅРёРµ РІРµСЂСЃРёРѕРЅРЅС‹РјРё СЃРЅРёРјРєР°РјРё РґРѕРєСѓРјРµРЅС‚Р° РІ СЂР°РјРєР°С… РѕРґРЅРѕРіРѕ Р·Р°РїСѓСЃРєР°."""

    SNAPSHOTS_SUBDIR = 'history'

    def __init__(self, base_dir, run_id=None):
        if run_id is None:
            run_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.run_id = run_id
        self.base_dir = os.path.join(base_dir, self.SNAPSHOTS_SUBDIR, run_id)
        os.makedirs(self.base_dir, exist_ok=True)
        self._snapshots = []
        self._counter = 0
        self._source_hash = None
        self._index_path = os.path.join(self.base_dir, '_index.json')

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
        """РЎРѕС…СЂР°РЅРёС‚СЊ СЃРЅРёРјРѕРє РґРѕРєСѓРјРµРЅС‚Р° СЃ РјРµС‚Р°РґР°РЅРЅС‹РјРё.

        Parameters
        ----------
        label : str
            РљСЂР°С‚РєР°СЏ РјРµС‚РєР° (РЅР°РїСЂРёРјРµСЂ, ``before_changes``, ``after_change_3``,
            ``after_rebuild``).
        data : dict
            РЎРѕСЃС‚РѕСЏРЅРёРµ РґРѕРєСѓРјРµРЅС‚Р°.
        metadata : dict | None
            Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ СЃРІРµРґРµРЅРёСЏ (РЅРѕРјРµСЂ РёР·РјРµРЅРµРЅРёСЏ, structural_element,
            С‚РёРї, РїСЂРёРјРµРЅРµРЅРѕ / РЅРµ РїСЂРёРјРµРЅРµРЅРѕ, СЃРѕРѕР±С‰РµРЅРёРµ РѕР± РѕС€РёР±РєРµ Рё С‚.Рї.).
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
                'snapshots': self._snapshots,
            }, f, ensure_ascii=False, indent=2)

    def list_snapshots(self):
        return list(self._snapshots)

    def load_snapshot(self, snapshot_id):
        match = next((s for s in self._snapshots if s['snapshot_id'] == snapshot_id), None)
        if not match:
            return None
        path = os.path.join(self.base_dir, match['filename'])
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def diff(self, from_id, to_id):
        """РљСЂР°С‚РєРёР№ diff РјРµР¶РґСѓ РґРІСѓРјСЏ СЃРЅРёРјРєР°РјРё: СЃРїРёСЃРѕРє item_id, С‡СЊРё revisions РёР·РјРµРЅРµРЅС‹."""
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
        """РЈРґР°Р»РёС‚СЊ РѕС‚СЂР°Р±РѕС‚Р°РЅРЅС‹Рµ СЃРЅРёРјРєРё, РѕСЃС‚Р°РІРёРІ СѓРєР°Р·Р°РЅРЅС‹Рµ (РёР»Рё РІСЃРµ, РµСЃР»Рё keep=None)."""
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