"""Система верификации результатов слияния НПА.

Проверяет целостность структуры JSON (соответствие описанию схемы в
``schema/``) и сверяет применённые изменения с ожидаемыми
результатами из ответов этапов (``work/answers/``). Любая оплошность
возвращается как структурированная ошибка с категорией, что позволяет
самообучающемуся системе классифицировать и исправлять её.
"""

import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

VALID_ITEM_TYPES = {
    'preamble', 'chapter', 'section', 'article', 'part', 'point',
    'subpoint', 'appendix', 'nested_appendix', 'structured_table',
    'paragraph',
}

VALID_MOD_TYPES = {
    'new_redaction', 'add', 'delete', 'change', 'correction',
    'renumber', 'editorial',
}

VALID_BODY_BLOCK_TYPES = {
    'paragraph', 'table', 'child_ref', 'table_header', 'table_fragment',
}

DATE_RE = re.compile(r'^\d{2}\.\d{2}\.\d{4}$')

MOD_BY_ID_RE = re.compile(r'^\d+_[a-z_]+_\S+')


class VerificationError:
    """Одиночная ошибка верификации с метаданными для самообучения."""

    __slots__ = ('category', 'element', 'message', 'severity', 'change_index',
                 'structural_element', 'remediation')

    def __init__(self, category, message, element=None, severity='error',
                 change_index=None, structural_element=None, remediation=None):
        self.category = category
        self.message = message
        self.element = element
        self.severity = severity
        self.change_index = change_index
        self.structural_element = structural_element
        self.remediation = remediation

    def to_dict(self):
        return {
            'category': self.category,
            'element': self.element,
            'message': self.message,
            'severity': self.severity,
            'change_index': self.change_index,
            'structural_element': self.structural_element,
            'remediation': self.remediation,
        }

    def __repr__(self):
        return (f"VerificationError(category={self.category!r}, "
                f"element={self.element!r}, msg={self.message!r})")


class VerificationResult:
    """Агрегированный результат полной верификации."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.change_outcomes = []

    @property
    def passed(self):
        return not self.has_errors()

    def has_errors(self):
        return any(e.severity == 'error' for e in self.errors)

    def add_error(self, category, message, element=None, change_index=None,
                  structural_element=None, remediation=None):
        self.errors.append(VerificationError(
            category=category, message=message, element=element, severity='error',
            change_index=change_index, structural_element=structural_element,
            remediation=remediation,
        ))

    def add_warning(self, category, message, element=None, change_index=None,
                    structural_element=None, remediation=None):
        self.warnings.append(VerificationError(
            category=category, message=message, element=element, severity='warning',
            change_index=change_index, structural_element=structural_element,
            remediation=remediation,
        ))

    def record_change_outcome(self, change_index, change, passed, reason=''):
        self.change_outcomes.append({
            'change_index': change_index,
            'structural_element': change.get('structural_element', ''),
            'type': change.get('type', ''),
            'revision_number': change.get('revision_number'),
            'passed': passed,
            'reason': reason,
        })

    def stats(self):
        by_cat = {}
        for e in self.errors:
            by_cat[e.category] = by_cat.get(e.category, 0) + 1
        by_warn = {}
        for w in self.warnings:
            by_warn[w.category] = by_warn.get(w.category, 0) + 1
        return {
            'errors_by_category': by_cat,
            'warnings_by_category': by_warn,
            'total_errors': len(self.errors),
            'total_warnings': len(self.warnings),
            'changes_total': len(self.change_outcomes),
            'changes_passed': sum(1 for c in self.change_outcomes if c['passed']),
            'changes_failed': sum(1 for c in self.change_outcomes if not c['passed']),
        }

    def to_dict(self):
        return {
            'passed': not self.has_errors(),
            'errors': [e.to_dict() for e in self.errors],
            'warnings': [w.to_dict() for w in self.warnings],
            'change_outcomes': self.change_outcomes,
            'stats': self.stats(),
        }


def _parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str), '%d.%m.%Y').date()
    except (ValueError, TypeError):
        return None


def _is_valid_date_format(date_str):
    if date_str is None or date_str == '':
        return True
    return bool(DATE_RE.match(str(date_str)))


def _expected_valid_to(valid_from):
    vf = _parse_date(valid_from)
    if vf is None:
        return None
    return (vf - timedelta(days=1)).strftime('%d.%m.%Y')


def _walk_items(data):
    root = data.get('npa_items_revision', []) if isinstance(data, dict) else []
    result = []
    def recurse(items):
        for item in items:
            result.append(item)
            recurse(item.get('item_children', []))
    recurse(root)
    return result


def _iter_revisions(item):
    revs = item.get('revisions', [])
    if not isinstance(revs, list):
        return []
    return revs


def _active_revision(item):
    revs = _iter_revisions(item)
    for rev in reversed(revs):
        if rev.get('valid_to') in (None, ''):
            return rev
    return revs[-1] if revs else None


class StructureVerifier:
    """Верификатор целостности структуры и соответствия ожидаемым изменениям.

    Правила взяты из ``schema/npa_json_schema.md`` и
    ``schema/element_hierarchy_rules.md``, а также из раздела 6
    ``AGENT_INSTRUCTION.md`` (ПРОВЕРКА СТРУКТУРЫ / ССЫЛОК / ДАТ / ИЗМЕНЕНИЙ).
    """

    def __init__(self):
        pass

    def verify(self, data, changes=None, source_data=None, change_log=None):
        """Запустить полную верификацию.

        Parameters
        ----------
        data : dict
            Результирующий документ (target NPA после применения изменений).
        changes : list[dict] | None
            Список изменений (из этапов 1-3), которые должны
            быть применены.
        source_data : dict | None
            Изменяющий НПА (для проверки формата ``modified_by_id``).
        change_log : list[dict] | None
            Журнал применённых изменений {structural_element, type, applied, error}
            — используется для сверки с ожидаемыми результатами.
        """
        result = VerificationResult()

        if not isinstance(data, dict):
            result.add_error('root_structure',
                             'РљРѕСЂРЅРµРІРѕР№ РѕР±СЉРµРєС‚ РЅРµ СЏРІР»СЏРµС‚СЃСЏ dict')
            return result

        if 'npa_items_revision' not in data:
            result.add_error('root_structure',
                             'РћС‚СЃСѓС‚СЃС‚РІСѓРµС‚ РѕР±СЏР·Р°С‚РµР»СЊРЅРѕРµ РїРѕР»Рµ npa_items_revision')
            return result

        items = _walk_items(data)

        self._verify_item_ids(items, result)
        self._verify_item_types(items, result)
        self._verify_item_levels(data, result)
        self._verify_tree_integrity(data, items, result)
        self._verify_revisions(data, items, result)
        self._verify_dates(data, items, source_data, result)
        self._verify_modified_by_format(items, source_data, result)
        self._verify_highlights(items, result)

        if changes is not None:
            self._verify_expected_changes(data, changes, result)

        if change_log is not None:
            self._verify_change_log(change_log, result)

        self._verify_no_inlined_children(data, result)
        self._verify_descriptions_not_full_html(changes, result)

        return result

    # ------------------------------------------------------------------
    # 1. Уникальность item_id
    # ------------------------------------------------------------------
    def _verify_item_ids(self, items, result):
        seen = {}
        for item in items:
            item_id = item.get('item_id')
            if not item_id:
                result.add_error('item_id_missing',
                                 'Р­Р»РµРјРµРЅС‚ Р±РµР· item_id', element=item.get('item_type'))
                continue
            if item_id in seen:
                result.add_error(
                    'item_id_duplicate',
                    f"Р”СѓР±Р»РёСЂСѓРµС‚СЃСЏ item_id '{item_id}'",
                    element=item_id,
                    remediation='Р”РѕР±Р°РІРёС‚СЊ СЃСѓС„С„РёРєСЃ _double_N Рє РґСѓР±Р»РёСЂСѓСЋС‰РµРјСѓ СЌР»РµРјРµРЅС‚Сѓ',
                )
            else:
                seen[item_id] = True

    # ------------------------------------------------------------------
    # 2. Допустимые item_type
    # ------------------------------------------------------------------
    def _verify_item_types(self, items, result):
        for item in items:
            itype = item.get('item_type')
            if itype not in VALID_ITEM_TYPES:
                result.add_error(
                    'item_type_invalid',
                    f"РќРµРґРѕРїСѓСЃС‚РёРјС‹Р№ item_type '{itype}' РґР»СЏ СЌР»РµРјРµРЅС‚Р° {item.get('item_id')}",
                    element=item.get('item_id'),
                    remediation='РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РѕРґРёРЅ РёР· РґРѕРїСѓСЃС‚РёРјС‹С… С‚РёРїРѕРІ РёР· СЃС…РµРјС‹',
                )

    # ------------------------------------------------------------------
    # 3. Корректность item_level (ход по дереву с учётом глубины)
    # ------------------------------------------------------------------
    def _verify_item_levels(self, data, result):
        root_items = data.get('npa_items_revision', [])
        def recurse(items, expected_level):
            for item in items:
                actual_level = item.get('item_level')
                if actual_level is None or actual_level != expected_level:
                    result.add_error(
                        'item_level_invalid',
                        f"item_level={actual_level} РЅРµ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ РѕР¶РёРґР°РµРјРѕРјСѓ "
                        f"{expected_level} РґР»СЏ СЌР»РµРјРµРЅС‚Р° {item.get('item_id')} "
                        f"(С‚РёРї {item.get('item_type')}, РЅРѕРјРµСЂ '{item.get('item_number')}')",
                        element=item.get('item_id'),
                        remediation='РЈСЃС‚Р°РЅРѕРІРёС‚СЊ item_level = (СѓСЂРѕРІРµРЅСЊ СЂРѕРґРёС‚РµР»СЏ + 1)',
                    )
                recurse(item.get('item_children', []), expected_level + 1)
        recurse(root_items, 1)

    # ------------------------------------------------------------------
    # 4. Целостность дерева: child_ref → существующий item_id;
    #    все дети имеют child_ref в body родителя
    # ------------------------------------------------------------------
    def _verify_tree_integrity(self, data, items, result):
        id_set = {item.get('item_id') for item in items if item.get('item_id')}

        for item in items:
            item_id = item.get('item_id')
            for rev in _iter_revisions(item):
                body = rev.get('body', []) if isinstance(rev.get('body'), list) else []
                for block in body:
                    if not isinstance(block, dict):
                        result.add_warning('body_block_invalid',
                                           f"Р‘Р»РѕРє body РЅРµ СЏРІР»СЏРµС‚СЃСЏ dict РІ {item_id}")
                        continue
                    btype = block.get('type')
                    if btype not in VALID_BODY_BLOCK_TYPES:
                        result.add_warning('body_block_type_unknown',
                                           f"РќРµРёР·РІРµСЃС‚РЅС‹Р№ С‚РёРї Р±Р»РѕРєР° body '{btype}' РІ {item_id}",
                                           element=item_id)
                    if btype == 'child_ref':
                        ref_id = block.get('item_id')
                        if not ref_id:
                            result.add_error('child_ref_broken',
                                             'child_ref Р±РµР· item_id', element=item_id)
                        elif ref_id not in id_set:
                            result.add_error(
                                'child_ref_broken',
                                f"child_ref СЃСЃС‹Р»Р°РµС‚СЃСЏ РЅР° РЅРµСЃСѓС‰РµСЃС‚РІСѓСЋС‰РёР№ item_id "
                                f"'{ref_id}' (РІ {item_id})",
                                element=item_id,
                                remediation='РџСЂРѕРІРµСЂРёС‚СЊ child_ref, РЅРµ СѓРґР°Р»С‘РЅ Р»Рё СЂРµР±С‘РЅРѕРє',
                            )
                orders = [b.get('order') for b in body if isinstance(b, dict) and 'order' in b]
                if orders and orders != list(range(1, len(orders) + 1)):
                    result.add_warning('body_order_invalid',
                                       f"РџРѕСЂСЏРґРѕРє Р±Р»РѕРєРѕРІ body РЅР°СЂСѓС€РµРЅ РІ {item_id}: {orders}",
                                       element=item_id)

        for item in items:
            children = item.get('item_children', [])
            if children:
                body_child_refs = set()
                for rev in _iter_revisions(item):
                    body = rev.get('body', []) if isinstance(rev.get('body'), list) else []
                    for block in body:
                        if isinstance(block, dict) and block.get('type') == 'child_ref':
                            body_child_refs.add(block.get('item_id'))
                for child in children:
                    cid = child.get('item_id')
                    if cid and cid not in body_child_refs:
                        result.add_warning(
                            'child_ref_missing',
                            f"Р РµР±С‘РЅРѕРє {cid} РµСЃС‚СЊ РІ item_children, РЅРѕ РЅРµС‚ СЃСЃС‹Р»РєРё "
                            f"child_ref РІ body СЌР»РµРјРµРЅС‚Р° {item.get('item_id')}",
                            element=item.get('item_id'),
                            remediation='Р”РѕР±Р°РІРёС‚СЊ child_ref РІ body СЂРѕРґРёС‚РµР»СЏ',
                        )

    # ------------------------------------------------------------------
    # 5. Ревизии: активность, valid_from / valid_to, непрерывность
    # ------------------------------------------------------------------
    def _verify_revisions(self, data, items, result):
        for item in items:
            item_id = item.get('item_id')
            revs = _iter_revisions(item)
            if not revs:
                result.add_error('revision_missing',
                                 f"Р­Р»РµРјРµРЅС‚ {item_id} РЅРµ РёРјРµРµС‚ СЂРµРІРёР·РёР№", element=item_id)
                continue

            active = []
            for idx, rev in enumerate(revs):
                vf = rev.get('valid_from')
                vt = rev.get('valid_to')
                if vf is None:
                    result.add_error('revision_valid_from_missing',
                                     f"Р РµРІРёР·РёСЏ {idx} СЌР»РµРјРµРЅС‚Р° {item_id} Р±РµР· valid_from",
                                     element=item_id)
                else:
                    if not _is_valid_date_format(vf):
                        result.add_error('date_format_invalid',
                                         f"valid_from '{vf}' РЅРµ РІ С„РѕСЂРјР°С‚Рµ DD.MM.YYYY "
                                         f"РІ СЂРµРІРёР·РёРё {idx} СЌР»РµРјРµРЅС‚Р° {item_id}",
                                         element=item_id)
                if vt is not None and not _is_valid_date_format(vt):
                    result.add_error('date_format_invalid',
                                     f"valid_to '{vt}' РЅРµ РІ С„РѕСЂРјР°С‚Рµ DD.MM.YYYY "
                                     f"РІ СЂРµРІРёР·РёРё {idx} СЌР»РµРјРµРЅС‚Р° {item_id}",
                                     element=item_id)
                if vt in (None, ''):
                    active.append(rev)

                if vf is not None and vt is not None:
                    if idx + 1 < len(revs):
                        next_vf = revs[idx + 1].get('valid_from')
                        if next_vf:
                            exp_vt = _expected_valid_to(next_vf)
                            if exp_vt is not None and vt != exp_vt:
                                result.add_warning('date_continuity',
                                                   f"valid_to '{vt}' != valid_from '{next_vf}' - 1 РґРµРЅСЊ "
                                                   f"(РѕР¶РёРґР°Р»РѕСЃСЊ {exp_vt}) РІ СЂРµРІРёР·РёРё {idx} СЌР»РµРјРµРЅС‚Р° {item_id}",
                                                   element=item_id)

            if len(active) > 1:
                result.add_error(
                    'revision_active_conflict',
                    f"Р­Р»РµРјРµРЅС‚ {item_id} РёРјРµРµС‚ {len(active)} Р°РєС‚РёРІРЅС‹С… СЂРµРІРёР·РёР№ (РґРѕР»Р¶РЅР° Р±С‹С‚СЊ 1)",
                    element=item_id,
                    remediation='РћСЃС‚Р°РІРёС‚СЊ С‚РѕР»СЊРєРѕ РѕРґРЅСѓ Р°РєС‚РёРІРЅСѓСЋ СЂРµРІРёР·РёСЋ (valid_to=null)',
                )

        head_rev = data.get('head_revision')
        if isinstance(head_rev, list):
            active_hr = [h for h in head_rev if h.get('valid_to') in (None, '')]
            if len(active_hr) > 1:
                result.add_warning('head_revision_active_conflict',
                                   f"head_revision РёРјРµРµС‚ {len(active_hr)} Р°РєС‚РёРІРЅС‹С… СЂРµРІРёР·РёР№")

    # ------------------------------------------------------------------
    # 6. Формат корневых дат
    # ------------------------------------------------------------------
    def _verify_dates(self, data, items, source_data, result):
        date_fields = ['date_pub', 'date_reg', 'date_signed',
                       'date_1st_reading', 'valid_from']
        if source_data:
            date_fields.append('date_passed')
        for field in date_fields:
            val = data.get(field)
            if val is not None and not _is_valid_date_format(val):
                result.add_error(
                    'date_format_invalid',
                    f"РљРѕСЂРЅРµРІРѕРµ РїРѕР»Рµ '{field}' = '{val}' РЅРµ РІ С„РѕСЂРјР°С‚Рµ DD.MM.YYYY",
                    element='root',
                )

    # ------------------------------------------------------------------
    # 7. modified_by_id format
    # ------------------------------------------------------------------
    def _verify_modified_by_format(self, items, source_data, result):
        source_npa_id = str(source_data.get('npa_id', '')) if source_data else ''
        for item in items:
            item_id = item.get('item_id')
            for rev in _iter_revisions(item):
                mbid = rev.get('modified_by_id')
                if mbid is None:
                    continue
                mbid_str = str(mbid)
                if source_npa_id:
                    if mbid_str == source_npa_id:
                        result.add_error(
                            'modified_by_id_bare',
                            f"modified_by_id '{mbid_str}' СЏРІР»СЏРµС‚СЃСЏ РіРѕР»С‹Рј РЅРѕРјРµСЂРѕРј РќРџРђ Р±РµР· СЃС‚СЂСѓРєС‚СѓСЂРЅРѕРіРѕ "
                            f"СЃСѓС„С„РёРєСЃР°. РўСЂРµР±СѓРµС‚СЃСЏ РїРѕР»РЅС‹Р№ item_id РёР·РјРµРЅСЏСЋС‰РµРіРѕ СЌР»РµРјРµРЅС‚Р° "
                            f"РІ С„РѕСЂРјР°С‚Рµ '{{npa_id}}_{{type}}_{{number}}'.",
                            element=item_id,
                            remediation='РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РїРѕР»РЅС‹Р№ item_id РёР·РјРµРЅСЏСЋС‰РµРіРѕ СЌР»РµРјРµРЅС‚Р° (РЅР°РїСЂРёРјРµСЂ, '
                                        '"37687_article_1_point_1"), Р° РЅРµ С‚РѕР»СЊРєРѕ РЅРѕРјРµСЂ РќРџРђ',
                        )
                        continue
                    if mbid_str.startswith(source_npa_id + '_'):
                        parts = mbid_str.split('_')
                        type_part = parts[1] if len(parts) > 1 else ''
                        if type_part not in VALID_ITEM_TYPES and type_part != 'article':
                            result.add_warning(
                                'modified_by_id_format',
                                f"modified_by_id '{mbid_str}' РёРјРµРµС‚ РЅРµРёР·РІРµСЃС‚РЅС‹Р№ С‚РёРї "
                                f"'{type_part}' РІ СЂРµРІРёР·РёРё СЌР»РµРјРµРЅС‚Р° {item_id}",
                                element=item_id,
                            )
                    elif not MOD_BY_ID_RE.match(mbid_str):
                        result.add_warning(
                            'modified_by_id_format',
                            f"modified_by_id '{mbid_str}' РЅРµ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ С„РѕСЂРјР°С‚Сѓ "
                            f"'{{npa_id}}_{{type}}_{{number}}' РІ СЌР»РµРјРµРЅС‚Рµ {item_id}",
                            element=item_id,
                            remediation='РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РїРѕР»РЅС‹Р№ item_id РёР·РјРµРЅСЏСЋС‰РµРіРѕ СЌР»РµРјРµРЅС‚Р°',
                        )

    # ------------------------------------------------------------------
    # 8. highlights
    # ------------------------------------------------------------------
    def _verify_highlights(self, items, result):
        for item in items:
            for rev in _iter_revisions(item):
                highlights = rev.get('highlights')
                if highlights is None:
                    continue
                if not isinstance(highlights, dict):
                    result.add_warning('highlights_invalid',
                                       f"highlights РЅРµ dict РІ {item.get('item_id')}")
                    continue
                for side in ('previous_edition', 'current_edition'):
                    sub = highlights.get(side)
                    if sub is not None and not isinstance(sub, dict):
                        result.add_warning('highlights_invalid',
                                           f"highlights.{side} РЅРµ dict РІ {item.get('item_id')}")

    # ------------------------------------------------------------------
    # 9. Проверка ожидаемых изменений (сверка с ответами этапов)
    # ------------------------------------------------------------------
    def _resolve_target(self, data, structural):
        from npa_processor.processing.element_ops import _find_existing_element_flexible
        if not structural:
            return None
        try:
            return _find_existing_element_flexible(data, structural, log_callback=None)
        except ValueError:
            return None

    def _verify_expected_changes(self, data, changes, result):
        for idx, change in enumerate(changes):
            ch_type = change.get('type', '').strip()
            structural = change.get('structural_element', '').strip()
            outcome = self._resolve_change_outcome(data, structural, ch_type, change)
            result.record_change_outcome(idx, change, outcome['passed'], outcome['reason'])
            if not outcome['passed']:
                result.add_error(
                    'change_not_applied',
                    outcome['reason'],
                    element=structural,
                    change_index=idx,
                    structural_element=structural,
                    remediation=outcome.get('remediation'),
                )

    def _resolve_change_outcome(self, data, structural, ch_type, change):
        structural_lower = structural.lower() if structural else ''

        if ch_type == 'add' and structural_lower == 'нпа':
            items = data.get('npa_items_revision', [])
            has_add = any(
                any(r.get('mod_type') == 'add' for r in _iter_revisions(item))
                for item in items
            )
            if has_add:
                return {'passed': True, 'reason': 'Р”РѕР±Р°РІР»РµРЅС‹ РЅРѕРІС‹Рµ СЌР»РµРјРµРЅС‚С‹ РЅР° РєРѕСЂРЅРµРІРѕР№ СѓСЂРѕРІРµРЅСЊ'}
            return {'passed': False,
                    'reason': f"Р­Р»РµРјРµРЅС‚ '{structural}' РЅРµ РЅР°Р№РґРµРЅ РІ СЂРµР·СѓР»СЊС‚Р°С‚Рµ",
                    'remediation': 'РџСЂРѕРІРµСЂРёС‚СЊ structural_element'}

        if ch_type == 'delete' or 'утрат' in structural_lower or structural_lower == 'law':
            if structural_lower in ('наименование', 'преамбула', 'нпа') or structural == 'law':
                target = self._resolve_target(data, structural) if structural not in ('law', '') else data
            else:
                target = self._resolve_target(data, structural)
            if target is None:
                return {'passed': False,
                        'reason': f"Р­Р»РµРјРµРЅС‚ '{structural}' РЅРµ РЅР°Р№РґРµРЅ РІ СЂРµР·СѓР»СЊС‚Р°С‚Рµ",
                        'remediation': 'РџСЂРѕРІРµСЂРёС‚СЊ structural_element'}
            all_revs = _iter_revisions(target)
            has_delete = any(r.get('mod_type') == 'delete' for r in all_revs)
            has_not_valid = any(r.get('not_valid') for r in all_revs)
            if has_delete or has_not_valid:
                return {'passed': True, 'reason': 'Р­Р»РµРјРµРЅС‚ РїРѕРјРµС‡РµРЅ РєР°Рє удалённый'}
            return {'passed': False,
                    'reason': f"Р­Р»РµРјРµРЅС‚ '{structural}' РЅРµ РёРјРµРµС‚ РїСЂРёР·РЅР°РєРѕРІ СѓРґР°Р»РµРЅРёСЏ (mod_type=delete РёР»Рё not_valid)",
                    'remediation': 'РџСЂРёРјРµРЅРёС‚СЊ delete: СѓСЃС‚Р°РЅРѕРІРёС‚СЊ not_valid РІ СЃС‚Р°СЂРѕР№ СЂРµРІРёР·РёРё'}

        if structural_lower == 'наименование':
            head_revs = data.get('head_revision', []) if isinstance(data.get('head_revision'), list) else []
            if any(r.get('mod_type') in ('change', 'new_redaction') for r in head_revs):
                return {'passed': True, 'reason': 'РќР°РёРјРµРЅРѕРІР°РЅРёРµ РќРџРђ РёР·РјРµРЅРµРЅРѕ'}
            return {'passed': False, 'reason': 'РќР°РёРјРµРЅРѕРІР°РЅРёРµ РќРџРђ РЅРµ РёР·РјРµРЅРµРЅРѕ'}

        target = self._resolve_target(data, structural)
        if target is None:
            return {'passed': False,
                    'reason': f"Р­Р»РµРјРµРЅС‚ '{structural}' РЅРµ РЅР°Р№РґРµРЅ РІ СЂРµР·СѓР»СЊС‚Р°С‚Рµ",
                    'remediation': 'РџСЂРѕРІРµСЂРёС‚СЊ РїСѓС‚СЊ structural_element'}

        if structural_lower.endswith(' наименование'):
            head_revs = target.get('head_revisions', [])
            if any(r.get('mod_type') in ('change', 'new_redaction') for r in head_revs):
                return {'passed': True, 'reason': 'Р­Р»РµРјРµРЅС‚ СЃ РёР·РјРµРЅС‘РЅРЅС‹Рј наименованиеРј'}
            return {'passed': False,
                    'reason': f"РќР°РёРјРµРЅРѕРІР°РЅРёРµ СЌР»РµРјРµРЅС‚Р° '{structural}' РЅРµ РёР·РјРµРЅРµРЅРѕ"}

        if structural_lower.endswith(' префикс'):
            return {'passed': True, 'reason': 'РџСЂРµС„РёРєСЃ РїСЂРёР»РѕР¶РµРЅРёСЏ РѕР±СЂР°Р±РѕС‚Р°РЅ'}

        if structural_lower == 'преамбула':
            rev = _active_revision(target)
            if rev and rev.get('mod_type') in ('new_redaction', 'change', 'delete'):
                return {'passed': True, 'reason': f"РџСЂРµР°РјР±СѓР»Р°: mod_type={rev.get('mod_type')}"}
            return {'passed': False, 'reason': 'РџСЂРµР°РјР±СѓР»Р° РЅРµ РёР·РјРµРЅРµРЅР°'}

        mod_type = ch_type if ch_type in VALID_MOD_TYPES else 'new_redaction'
        rev = _active_revision(target)
        if rev is not None and rev.get('mod_type') == mod_type:
            return {'passed': True,
                    'reason': f"Р­Р»РµРјРµРЅС‚ РёРјРµРµС‚ Р°РєС‚РёРІРЅСѓСЋ СЂРµРІРёР·РёСЋ СЃ mod_type={mod_type}"}

        all_revs = _iter_revisions(target)
        if any(r.get('mod_type') == mod_type for r in all_revs):
            return {'passed': True,
                    'reason': f"Р­Р»РµРјРµРЅС‚ РёРјРµРµС‚ СЂРµРІРёР·РёСЋ СЃ mod_type={mod_type}"}
        return {'passed': False,
                'reason': f"Р­Р»РµРјРµРЅС‚ '{structural}' РЅРµ РёРјРµРµС‚ СЂРµРІРёР·РёРё СЃ mod_type={mod_type}",
                'remediation': 'РџРѕРІС‚РѕСЂРЅРѕ РїСЂРёРјРµРЅРёС‚СЊ РёР·РјРµРЅРµРЅРёРµ'}

    def _verify_change_log(self, change_log, result):
        counts = {}
        for entry in change_log:
            ct = entry.get('type', 'unknown')
            counts[ct] = counts.get(ct, 0) + 1
            if not entry.get('applied'):
                result.add_warning(
                    'change_skipped',
                    f"РР·РјРµРЅРµРЅРёРµ РЅРµ РїСЂРёРјРµРЅРµРЅРѕ: {entry.get('structural_element')} "
                    f"({ct}) вЂ” {entry.get('error', '')}",
                )
        result._change_log_counts = counts

    def _verify_no_inlined_children(self, data, result):
        """Check that children are NOT inlined as HTML in parent body blocks."""
        items = _walk_items(data)
        for item in items:
            if not item.get('item_children'):
                continue
            item_id = item.get('item_id')
            for rev in _iter_revisions(item):
                body = rev.get('body', []) if isinstance(rev.get('body'), list) else []
                for block in body:
                    if not isinstance(block, dict):
                        continue
                    if block.get('type') != 'paragraph':
                        continue
                    html = block.get('html_text', '')
                    if not html or not isinstance(html, str):
                        continue
                    if '<p>' not in html and '</p>' not in html:
                        continue
                    soup = BeautifulSoup(html, 'html.parser')
                    paragraphs = soup.find_all('p')
                    if len(paragraphs) <= 1:
                        continue
                    has_child_ref = any(
                        b.get('type') == 'child_ref' for b in body
                    )
                    if not has_child_ref:
                        continue
                    result.add_warning(
                        'children_inlined_in_body',
                        f"Р’ {item_id} РѕР±РЅР°СЂСѓР¶РµРЅС‹ РјРЅРѕР¶РµСЃС‚РІРµРЅРЅС‹Рµ <p> РІ body Р±Р»РѕРєРµ, "
                        f"РЅРѕ РµСЃС‚СЊ child_ref вЂ” РІРѕР·РјРѕР¶РЅРѕ, РґРµС‚Рё РІР»РѕР¶РµРЅС‹ РЅР°РїСЂСЏРјСѓСЋ РІ HTML",
                        element=item_id,
                        remediation='Р’С‹РЅРµСЃС‚Рё РґРµС‚РµР№ РёР· body РІ item_children, Р·Р°РјРµРЅРёС‚СЊ РЅР° child_ref',
                    )
                    break

    def _verify_descriptions_not_full_html(self, changes, result):
        """Check that change descriptions don't contain full article HTML."""
        if not changes:
            return
        for idx, change in enumerate(changes):
            ch_type = change.get('type', '').strip()
            desc = change.get('description', '')
            if not desc or not isinstance(desc, str):
                continue
            if ch_type in ('change', 'delete'):
                if '<p>' in desc and '</p>' in desc and len(desc) > 500:
                    result.add_warning(
                        'description_contains_full_html',
                        f"Change #{idx} ({change.get('structural_element', '')}): "
                        f"description СЃРѕРґРµСЂР¶РёС‚ РїРѕР»РЅС‹Р№ HTML (>500 СЃРёРјРІРѕР»РѕРІ), "
                        f"РІРѕР·РјРѕР¶РЅРѕ, СЃРєРѕРїРёСЂРѕРІР°РЅ С‚РµРєСЃС‚ РёР· РёР·РјРµРЅСЏСЋС‰РµРіРѕ РќРџРђ",
                        change_index=idx,
                        remediation='Р—Р°РјРµРЅРёС‚СЊ description РЅР° С‚РѕС‡РЅСѓСЋ РёРЅСЃС‚СЂСѓРєС†РёСЋ Р±РµР· РїРѕР»РЅРѕРіРѕ HTML',
                    )
            elif ch_type in ('new_redaction', 'add'):
                if '<p>' in desc or '<' in desc:
                    result.add_error(
                        'description_contains_html_for_new_redaction',
                        f"Change #{idx} ({change.get('structural_element', '')}): "
                        f"description РґР»СЏ new_redaction/add СЃРѕРґРµСЂР¶РёС‚ HTML С‚РµРіРё",
                        change_index=idx,
                        remediation='Р—Р°РјРµРЅРёС‚СЊ description РЅР° Р°Р±СЃРѕР»СЋС‚РЅС‹Рµ РЅРѕРјРµСЂР° Р°Р±Р·Р°С†РµРІ (РЅР°РїСЂРёРјРµСЂ, "5-7")',
                    )



