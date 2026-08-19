"""Самообучающийся движок для NPA JSON Agent.

Механизм самообучения реализует **замкнутый цикл обратной связи**:

1. **Запись результатов** — после каждого запуска пайплайна сохраняются
   детальные результаты верификации, исходы каждого изменения и сообщения
   об ошибках (не только счётчики, как раньше).
2. **Консультация перед применением** — перед применением изменений агент
   запрашивает проверенные маппинги (`get_reliable_mapping`) и
   рекомендации по восстановлению при ошибке связанной структуры
   (`get_suggestions_for_element`).
3. **Анализ провалов** — `get_failure_patterns` группирует исторические
   ошибки по категории и предлагает алгоритмические улучшения.
4. **Запоминание успешных обходных путей** — `record_recovery` фиксирует,
   какое именно исправление сработало для конкретного сценария.

Любая оплошность ведёт к изменению алгоритма: результаты верификации
превращаются в конкретные рекомендации, которые используются в
последующих запусках.
"""

import copy
import json
import logging
import os
from collections import defaultdict
from datetime import datetime

from npa_processor.paths import LEARNING_DIR, load_json, save_json

logger = logging.getLogger(__name__)


class LearningEngine:
    """Центральный движок самообучения.

    Хранилища находятся в ``learning/`` (в корне проекта, как описано
    в ``AGENT_INSTRUCTION.md`` / ``README.md``) и исключаются из git.
    """

    LOG_FILE = os.path.join(LEARNING_DIR, 'learning_log.json')
    MAPPINGS_FILE = os.path.join(LEARNING_DIR, 'element_mappings.json')
    PROMPT_FEEDBACK_FILE = os.path.join(LEARNING_DIR, 'prompt_feedback.json')
    VERIFICATION_LOG_FILE = os.path.join(LEARNING_DIR, 'verification_log.json')
    CHANGE_OUTCOMES_FILE = os.path.join(LEARNING_DIR, 'change_outcomes.json')
    RECOVERY_LOG_FILE = os.path.join(LEARNING_DIR, 'recovery_log.json')
    RUN_LOG_FILE = os.path.join(LEARNING_DIR, 'run_log.json')
    ERROR_EXAMPLES_FILE = os.path.join(LEARNING_DIR, 'error_examples.json')
    BUG_FIXES_FILE = os.path.join(LEARNING_DIR, 'bug_fixes.json')
    SEED_EXAMPLES_FILE = os.path.join(LEARNING_DIR, 'seed_examples.json')

    def __init__(self):
        os.makedirs(LEARNING_DIR, exist_ok=True)
        self._log = load_json(self.LOG_FILE, [])
        self._mappings = load_json(self.MAPPINGS_FILE, {})
        self._prompt_feedback = load_json(self.PROMPT_FEEDBACK_FILE, {})
        self._verification_log = load_json(self.VERIFICATION_LOG_FILE, [])
        self._change_outcomes = load_json(self.CHANGE_OUTCOMES_FILE, [])
        self._recovery_log = load_json(self.RECOVERY_LOG_FILE, [])
        self._run_log = load_json(self.RUN_LOG_FILE, [])
        self._error_examples = load_json(self.ERROR_EXAMPLES_FILE, [])
        self._bug_fixes = load_json(self.BUG_FIXES_FILE, [])
        self._seed_examples = load_json(self.SEED_EXAMPLES_FILE, [])

    # ------------------------------------------------------------------
    # 1. Запись итогового результата запуска
    # ------------------------------------------------------------------
    def record_run(self, source_npa_id, target_npa_id, changes_applied,
                   changes_failed, manual_corrections, notes=''):
        entry = {
            'timestamp': datetime.now().isoformat(),
            'source_npa_id': str(source_npa_id),
            'target_npa_id': str(target_npa_id),
            'changes_applied': changes_applied,
            'changes_failed': changes_failed,
            'manual_corrections': manual_corrections,
            'notes': notes,
        }
        self._log.append(entry)
        save_json(self.LOG_FILE, self._log)

    def record_detailed_run(self, source_npa_id, target_npa_id, changes_applied,
                            changes_failed, manual_corrections, notes='',
                            changes_detail=None, verification=None,
                            elapsed_seconds=None):
        """Р Р°СЃС€РёСЂРµРЅРЅР°СЏ Р·Р°РїРёСЃСЊ Р·Р°РїСѓСЃРєР° СЃ РїРѕР»РЅРѕР№ РёСЃС‚РѕСЂРёРµР№.

        ``changes_detail`` вЂ” СЃРїРёСЃРѕРє ``{"structural_element", "type",
        "applied", "error"}`` РґР»СЏ РєР°Р¶РґРѕРіРѕ изменения.
        ``verification`` вЂ” СЃРµСЂРёР°Р»РёР·РѕРІР°РЅРЅС‹Р№ ``VerificationResult``.
        """
        entry = {
            'timestamp': datetime.now().isoformat(),
            'source_npa_id': str(source_npa_id),
            'target_npa_id': str(target_npa_id),
            'changes_applied': changes_applied,
            'changes_failed': changes_failed,
            'manual_corrections': manual_corrections,
            'notes': notes,
            'elapsed_seconds': elapsed_seconds,
        }
        self.record_run(source_npa_id, target_npa_id, changes_applied,
                        changes_failed, manual_corrections, notes)

        detailed = {
            'timestamp': entry['timestamp'],
            'source_npa_id': str(source_npa_id),
            'target_npa_id': str(target_npa_id),
            'changes_applied': changes_applied,
            'changes_failed': changes_failed,
            'notes': notes,
            'changes_detail': changes_detail or [],
            'verification': verification or {},
            'elapsed_seconds': elapsed_seconds,
        }
        self._run_log.append(detailed)
        save_json(self.RUN_LOG_FILE, self._run_log)

    # ------------------------------------------------------------------
    # 2. Маппинги structural_element -> item_id
    # ------------------------------------------------------------------
    def record_mapping(self, structural_element, item_id, success, source_context='',
                       error_category=None, error_message=None):
        """Записать результат разрешения structural_element → item_id.

        РўРµРїРµСЂСЊ Р·Р°РїРёСЃСЊ РґРµР»Р°РµС‚СЃСЏ **РїРѕСЃР»Рµ** С„Р°РєС‚РёС‡РµСЃРєРѕРіРѕ РїСЂРёРјРµРЅРµРЅРёСЏ изменения,
        РїРѕСЌС‚РѕРјСѓ success РѕС‚СЂР°Р¶Р°РµС‚ РЅРµ РїСЂРѕСЃС‚Рѕ РїРѕРёСЃРє элемента, Р° РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ
        РІСЃРµРіРѕ РїСЂРёРјРµРЅРµРЅРёСЏ изменения Рє СЌС‚РѕРјСѓ element_id.
        """
        key = structural_element
        if key not in self._mappings:
            self._mappings[key] = {
                'item_id': item_id,
                'success_count': 0,
                'fail_count': 0,
                'source_context': source_context,
                'last_used': datetime.now().isoformat(),
                'error_categories': {},
            }
        rec = self._mappings[key]
        rec['item_id'] = item_id
        rec['last_used'] = datetime.now().isoformat()
        if success:
            rec['success_count'] += 1
            rec.pop('last_error', None)
        else:
            rec['fail_count'] += 1
            rec['last_error'] = datetime.now().isoformat()
            if error_category:
                cats = rec.setdefault('error_categories', {})
                cats[error_category] = cats.get(error_category, 0) + 1
            if error_message:
                rec['last_error_message'] = error_message
        save_json(self.MAPPINGS_FILE, self._mappings)


    def get_reliable_mapping(self, structural_element):
        """Вернуть проверенный item_id или None.

        РќР°РґС‘Р¶РЅС‹Рј СЃС‡РёС‚Р°РµС‚СЃСЏ РјР°РїРїРёРЅРі, РіРґРµ ``success_count > fail_count`` Рё
        ``success_count >= 1`` (С‚.Рµ. С…РѕС‚СЏ Р±С‹ РѕРґРёРЅ СѓСЃРїРµС€РЅС‹Р№ РѕРїС‹С‚).
        """
        rec = self._mappings.get(structural_element)
        if not rec:
            return None
        success = rec.get('success_count', 0)
        fail = rec.get('fail_count', 0)
        if success > 0 and success > fail:
            item_id = rec.get('item_id')
            if item_id is not None:
                return item_id
        return None

    def get_reliable_mappings(self, structural_elements):
        """Пакетный запрос проверенных маппингов."""
        result = {}
        for se in structural_elements:
            mapped = self.get_reliable_mapping(se)
            if mapped is not None:
                result[se] = mapped
        return result



    # ------------------------------------------------------------------
    # 4. Р РµР·СѓР»СЊС‚Р°С‚С‹ РІРµСЂРёС„РёРєР°С†РёРё Рё РёСЃС…РѕРґС‹ РёР·РјРµРЅРµРЅРёР№
    # ------------------------------------------------------------------
    def record_verification_result(self, run_timestamp, source_npa_id,
                                   target_npa_id, verification):
        """Сохранить результат полной верификации для запуска."""
        entry = {
            'timestamp': run_timestamp,
            'source_npa_id': str(source_npa_id),
            'target_npa_id': str(target_npa_id),
            'passed': verification.get('passed', False) if verification else False,
            'stats': verification.get('stats', {}) if verification else {},
            'errors': verification.get('errors', []) if verification else [],
            'warnings': verification.get('warnings', []) if verification else [],
            'change_outcomes': verification.get('change_outcomes', []) if verification else [],
        }
        self._verification_log.append(entry)
        save_json(self.VERIFICATION_LOG_FILE, self._verification_log)
        return entry

    def record_change_outcome(self, structural_element, change_type, applied,
                              structurally_valid, error_category=None,
                              error_message=None, source_context=''):
        """Записать исход конкретного изменения (после применения + верификации)."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'structural_element': structural_element,
            'change_type': change_type,
            'applied': applied,
            'structurally_valid': structurally_valid,
            'error_category': error_category,
            'error_message': error_message,
            'source_context': source_context,
        }
        self._change_outcomes.append(entry)
        save_json(self.CHANGE_OUTCOMES_FILE, self._change_outcomes)

    # ------------------------------------------------------------------
    # 5. Система обратимых исправлений (recovery)
    # ------------------------------------------------------------------
    def record_recovery(self, structural_element, error_category, suggestion,
                        success, source_context=''):
        """Записать, сработало ли предложенное обходное решение."""
        key = f"{structural_element}||{error_category}"
        existing = None
        for entry in self._recovery_log:
            if entry.get('key') == key:
                existing = entry
                break
        if existing is None:
            existing = {
                'key': key,
                'structural_element': structural_element,
                'error_category': error_category,
                'suggestion': suggestion,
                'success_count': 0,
                'fail_count': 0,
                'source_context': source_context,
                'last_used': datetime.now().isoformat(),
            }
            self._recovery_log.append(existing)
        if success:
            existing['success_count'] += 1
        else:
            existing['fail_count'] += 1
        existing['last_used'] = datetime.now().isoformat()
        existing['suggestion'] = suggestion
        save_json(self.RECOVERY_LOG_FILE, self._recovery_log)

    def get_recovery_suggestion(self, structural_element, error_category):
        """Р’РµСЂРЅСѓС‚СЊ РїСЂРѕРІРµСЂРµРЅРЅРѕРµ РѕР±С…РѕРґРЅРѕРµ СЂРµС€РµРЅРёРµ РґР»СЏ СЃРѕС‡РµС‚Р°РЅРёСЏ СЌР»РµРјРµРЅС‚+ошибка."""
        key = f"{structural_element}||{error_category}"
        for entry in self._recovery_log:
            if entry.get('key') == key:
                sc = entry.get('success_count', 0)
                fc = entry.get('fail_count', 0)
                if sc > 0 and sc >= fc:
                    return entry.get('suggestion')
        return None

    # ------------------------------------------------------------------
    # 6. Анализ паттернов провалов → улучшение алгоритма
    # ------------------------------------------------------------------
    def get_failure_patterns(self, limit=20):
        """Сгруппировать исторические ошибки и вернуть рекомендации.

        Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє РїР°С‚С‚РµСЂРЅРѕРІ:
        ``{"structural_element", "error_category", "count", "suggestion"}``.
        Р›СЋР±Р°СЏ РѕРїР»РѕС€РЅРѕСЃС‚СЊ РїСЂРёРІРѕРґРёС‚ Рє РєРѕРЅРєСЂРµС‚РЅРѕРјСѓ Р°Р»РіРѕСЂРёС‚РјРёС‡РµСЃРєРѕРјСѓ СѓР»СѓС‡С€РµРЅРёСЋ.
        """
        by_key = defaultdict(list)
        for entry in self._change_outcomes:
            if entry.get('applied') and entry.get('structurally_valid'):
                continue
            se = entry.get('structural_element', '')
            cat = entry.get('error_category') or 'unknown'
            by_key[(se, cat)].append(entry)

        patterns = []
        for (se, cat), entries in by_key.items():
            patterns.append({
                'structural_element': se,
                'error_category': cat,
                'count': len(entries),
                'sample_error': entries[-1].get('error_message', '')[:300],
                'suggestion': self._suggest_for_pattern(se, cat, entries),
            })
        patterns.sort(key=lambda p: p['count'], reverse=True)
        return patterns[:limit]

    @staticmethod
    def _suggest_for_pattern(structural_element, category, entries):
        """РЎРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ РєРѕРЅРєСЂРµС‚РЅРѕРµ Р°Р»РіРѕСЂРёС‚РјРёС‡РµСЃРєРѕРµ СѓР»СѓС‡С€РµРЅРёРµ РґР»СЏ РїР°С‚С‚РµСЂРЅР°."""
        suggestions = []
        if category in ('item_id_duplicate',):
            suggestions.append('Р”РѕР±Р°РІРёС‚СЊ СЃСѓС„С„РёРєСЃ _double_N Рє РєРѕРЅС„Р»РёРєС‚СѓСЋС‰РµРјСѓ item_id')
        if category in ('child_ref_broken', 'child_ref_missing'):
            suggestions.append('Синхронизировать child_ref в body с item_children после применения')
        if category in ('item_level_invalid',):
            suggestions.append('Пересчитать item_level для всех потомков по глубине дерева')
        if category in ('date_format_invalid', 'date_continuity'):
            suggestions.append('РџСЂРѕРІРµСЂРёС‚СЊ формат РґР°С‚ DD.MM.Y Рё РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ valid_to = valid_from - 1 РґРµРЅСЊ')
        if category in ('modified_by_id_format',):
            suggestions.append('РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РџРћР›РќР«Р™ item_id РёСЃС‚РѕС‡РЅРёРєР°, Р° РЅРµ С‚РѕР»СЊРєРѕ npa_id')
        if category in ('change_not_applied', 'revision_missing'):
            se = structural_element.lower() if structural_element else ''
            if 'СЃС‚Р°С‚СЊ' in se:
                suggestions.append(
                    "РџСЂРѕРІРµСЂРёС‚СЊ РЅСѓРјРµСЂР°С†РёСЋ: СЃС‚Р°С‚СЊСЏ РјРѕР¶РµС‚ Р±С‹С‚СЊ РІР»РѕР¶РµРЅР° РІ РіР»Р°РІСѓ/раздел. "
                    "РџРѕРїСЂРѕР±РѕРІР°С‚СЊ РїРѕРёСЃРє С‡РµСЂРµР· find_element_in_chapters_or_sections."
                )
            elif 'часть' in se or 'пункт' in se or 'РїРѕРґпункт' in se:
                suggestions.append(
                    "РџСЂРѕРІРµСЂРёС‚СЊ РёРµСЂР°СЂС…РёСЋ: часть/пункт/РїРѕРґпункт РјРѕР¶РµС‚ РЅР°С…РѕРґРёС‚СЊСЃСЏ РІРЅСѓС‚СЂРё "
                    "РґСЂСѓРіРѕРіРѕ СЂРѕРґРёС‚РµР»СЏ РїРѕСЃР»Рµ new_redaction СЃРѕСЃРµРґРЅРµР№ статьи."
                )
            else:
                suggestions.append(
                    "РџСЂРѕРІРµСЂРёС‚СЊ путь structural_element: РІРѕР·РјРѕР¶РЅРѕ, С‚СЂРµР±СѓРµС‚СЃСЏ "
                    "СЂР°СЃРєСЂС‹С‚РёРµ not_found С‡РµСЂРµР· РјР°РїРїРёРЅРі РёР· learn/element_mappings."
                )
        if not suggestions:
            suggestions.append(f"Р”РѕР±Р°РІРёС‚СЊ Р·Р°РїРёСЃСЊ РІ element_mappings СЃ РєРѕСЂСЂРµРєС‚РЅС‹Рј item_id РґР»СЏ '{structural_element}'")
        return '; '.join(suggestions)

    def get_suggestions_for_element(self, structural_element):
        """Р’РµСЂРЅСѓС‚СЊ РІСЃРµ РёР·РІРµСЃС‚РЅС‹Рµ СЂРµРєРѕРјРµРЅРґР°С†РёРё РґР»СЏ РєРѕРЅРєСЂРµС‚РЅРѕРіРѕ элемента."""
        rec = self._mappings.get(structural_element)
        if not rec:
            return []
        cats = rec.get('error_categories', {})
        suggestions = []
        for cat in sorted(cats, key=lambda c: cats[c], reverse=True):
            sug = self.get_recovery_suggestion(structural_element, cat)
            if sug:
                suggestions.append({'category': cat, 'count': cats[cat], 'suggestion': sug})
            else:
                patterns = self.get_failure_patterns()
                for p in patterns:
                    if p['structural_element'] == structural_element and p['error_category'] == cat:
                        suggestions.append({'category': cat, 'count': cats[cat], 'suggestion': p['suggestion']})
                        break
        return suggestions

    # ------------------------------------------------------------------
    # 7. РђРіСЂРµРіРёСЂРѕРІР°РЅРЅР°СЏ СЃС‚Р°С‚РёСЃС‚РёРєР°
    # ------------------------------------------------------------------
    def get_stats(self):
        total_runs = len(self._log)
        total_applied = sum(e.get('changes_applied', 0) for e in self._log)
        total_failed = sum(e.get('changes_failed', 0) for e in self._log)
        total_corrections = sum(len(e.get('manual_corrections', [])) for e in self._run_log)
        reliable_mappings = sum(
            1 for rec in self._mappings.values()
            if rec.get('success_count', 0) > rec.get('fail_count', 0)
        )
        return {
            'total_runs': total_runs,
            'total_changes_applied': total_applied,
            'total_changes_failed': total_failed,
            'total_manual_corrections': total_corrections,
            'reliable_mappings': reliable_mappings,
            'total_verification_passes': sum(
                1 for e in self._verification_log if e.get('passed')
            ),
            'total_verification_fails': sum(
                1 for e in self._verification_log if not e.get('passed')
            ),
            'total_recoveries_attempted': len(self._recovery_log),
            'total_recoveries_successful': sum(
                1 for e in self._recovery_log if e.get('success_count', 0) > e.get('fail_count', 0)
            ),
        }

    def summarize_for_agent(self):
        lines = []
        stats = self.get_stats()
        lines.append(f"# РЎР°РјРѕРѕР±СѓС‡РµРЅРёРµ: СЃС‚Р°С‚РёСЃС‚РёРєР° ({stats['total_runs']} Р·Р°РїСѓСЃРєРѕРІ)")
        lines.append(f"- РџСЂРёРјРµРЅРµРЅРѕ РёР·РјРµРЅРµРЅРёР№: {stats['total_changes_applied']}")
        lines.append(f"- РћС€РёР±РѕРє РїСЂРёРјРµРЅРµРЅРёСЏ: {stats['total_changes_failed']}")
        lines.append(f"- Р’РµСЂРёС„РёРєР°С†РёР№ РїСЂРѕС€Р»Р°: {stats['total_verification_passes']}")
        lines.append(f"- Р’РµСЂРёС„РёРєР°С†РёР№ РїСЂРѕРІР°Р»РµРЅРѕ: {stats['total_verification_fails']}")
        lines.append(f"- РќР°РґС‘Р¶РЅС‹С… РјР°РїРїРёРЅРіРѕРІ: {stats['reliable_mappings']}")
        lines.append(f"- Р РµРєР°РІРµСЂРё РїРѕРїС‹С‚РѕРє: {stats['total_recoveries_attempted']}")
        lines.append(f"- Р РµРєР°РІРµСЂРё СѓСЃРїРµС€РЅС‹С…: {stats['total_recoveries_successful']}")
        lines.append("")
        lines.append("## РџРѕСЃР»РµРґРЅРёРµ Р·Р°РїСѓСЃРєРё")
        for entry in self._log[-5:]:
            ts = entry.get('timestamp', '')[:19]
            lines.append(
                f"- {ts}: source={entry.get('source_npa_id')}, "
                f"target={entry.get('target_npa_id')}, "
                f"applied={entry.get('changes_applied')}, "
                f"failed={entry.get('changes_failed')}, "
                f"status={entry.get('notes', '')}"
            )
        lines.append("")
        lines.append("## РўРѕРї-5 РїР°С‚С‚РµСЂРЅРѕРІ РїСЂРѕРІР°Р»РѕРІ")
        for p in self.get_failure_patterns(limit=5):
            lines.append(
                f"- '{p['structural_element']}' [{p['error_category']}]: "
                f"{p['count']} СЂР°Р· вЂ” {p['suggestion']}"
            )
        if not self.get_failure_patterns(limit=5):
            lines.append("- РќРµС‚ Р·Р°С„РёРєСЃРёСЂРѕРІР°РЅРЅС‹С… РїР°С‚С‚РµСЂРЅРѕРІ РїСЂРѕРІР°Р»РѕРІ")
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # 8. Характерные примеры ошибок
    # ------------------------------------------------------------------
    def record_error_example(self, structural_element, error_category, error_message,
                             context=None, source_npa_id='', target_npa_id=''):
        """Зафиксировать характерный пример ошибки для обучения.

        Parameters
        ----------
        structural_element : str
            РЎС‚СЂСѓРєС‚СѓСЂРЅС‹Р№ СЌР»РµРјРµРЅС‚, РЅР° РєРѕС‚РѕСЂРѕРј РїСЂРѕРёР·РѕС€Р»Р° ошибка.
        error_category : str
            РљР°С‚РµРіРѕСЂРёСЏ РѕС€РёР±РєРё (СЃРј. ``VerificationError.category``).
        error_message : str
            РўРµРєСЃС‚ РѕС€РёР±РєРё.
        context : dict | None
            Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Р№ РєРѕРЅС‚РµРєСЃС‚ (С‚РёРї изменения, РёРЅРґРµРєСЃ, РґР°РЅРЅС‹Рµ Рё С‚.Рї.).
        source_npa_id : str
            РР·РјРµРЅСЏСЋС‰РёР№ РќРџРђ.
        target_npa_id : str
            Целевой НПА.
        """
        entry = {
            'timestamp': datetime.now().isoformat(),
            'source_npa_id': str(source_npa_id),
            'target_npa_id': str(target_npa_id),
            'structural_element': structural_element,
            'error_category': error_category,
            'error_message': error_message,
            'context': context or {},
        }
        self._error_examples.append(entry)
        save_json(self.ERROR_EXAMPLES_FILE, self._error_examples)

    def get_error_examples(self, structural_element=None, error_category=None, limit=50):
        """Р’РµСЂРЅСѓС‚СЊ С…Р°СЂР°РєС‚РµСЂРЅС‹Рµ РїСЂРёРјРµСЂС‹ ошибок СЃ С„РёР»СЊС‚СЂР°С†РёРµР№."""
        result = list(self._error_examples)
        if structural_element is not None:
            result = [e for e in result if e.get('structural_element') == structural_element]
        if error_category is not None:
            result = [e for e in result if e.get('error_category') == error_category]
        result.sort(key=lambda e: e.get('timestamp', ''), reverse=True)
        return result[:limit]

    # ------------------------------------------------------------------
    # 9. Отслеживание исправлений багов
    # ------------------------------------------------------------------
    def record_bug_fix(self, bug_description, fix_description, applied_to=None,
                       verification_before=None, verification_after=None,
                       source_npa_id='', target_npa_id='', success=True):
        """Зафиксировать исправление бага, обнаруженного и применённого агентом.

        Parameters
        ----------
        bug_description : str
            РћРїРёСЃР°РЅРёРµ РѕР±РЅР°СЂСѓР¶РµРЅРЅРѕРіРѕ Р±Р°РіР°.
        fix_description : str
            РћРїРёСЃР°РЅРёРµ РїСЂРёРјРµРЅС‘РЅРЅРѕРіРѕ РёСЃРїСЂР°РІР»РµРЅРёСЏ.
        applied_to : list[str] | None
            РЎРїРёСЃРѕРє ``item_id``, Рє РєРѕС‚РѕСЂС‹Рј Р±С‹Р»Рѕ РїСЂРёРјРµРЅРµРЅРѕ РёСЃРїСЂР°РІР»РµРЅРёРµ.
        verification_before : dict | None
            РЎС‚Р°С‚РёСЃС‚РёРєР° РІРµСЂРёС„РёРєР°С†РёРё РґРѕ РёСЃРїСЂР°РІР»РµРЅРёСЏ.
        verification_after : dict | None
            РЎС‚Р°С‚РёСЃС‚РёРєР° РІРµСЂРёС„РёРєР°С†РёРё РїРѕСЃР»Рµ РёСЃРїСЂР°РІР»РµРЅРёСЏ.
        source_npa_id : str
            РР·РјРµРЅСЏСЋС‰РёР№ РќРџРђ.
        target_npa_id : str
            Целевой НПА.
        success : bool
            Р‘С‹Р»Рѕ Р»Рё РёСЃРїСЂР°РІР»РµРЅРёРµ СѓСЃРїРµС€РЅС‹Рј.
        """
        entry = {
            'timestamp': datetime.now().isoformat(),
            'source_npa_id': str(source_npa_id),
            'target_npa_id': str(target_npa_id),
            'bug_description': bug_description,
            'fix_description': fix_description,
            'applied_to': applied_to or [],
            'verification_before': verification_before or {},
            'verification_after': verification_after or {},
            'success': success,
        }
        self._bug_fixes.append(entry)
        save_json(self.BUG_FIXES_FILE, self._bug_fixes)


    # 10. Seed training examples (preloaded correct/incorrect patterns)
    # ------------------------------------------------------------------
    def get_seed_examples(self, category=None, subcategory=None, limit=20):
        """Р’РµСЂРЅСѓС‚СЊ С…Р°СЂР°РєС‚РµСЂРЅС‹Рµ РїСЂРёРјРµСЂС‹ РґР»СЏ РѕР±СѓС‡РµРЅРёСЏ РР.

        Parameters
        ----------
        category : str | None
            Р¤РёР»СЊС‚СЂ РїРѕ РєР°С‚РµРіРѕСЂРёРё (РЅР°РїСЂРёРјРµСЂ, ``"highlights"``).
        subcategory : str | None
            Р¤РёР»СЊС‚СЂ РїРѕ РїРѕРґРєР°С‚РµРіРѕСЂРёРё (РЅР°РїСЂРёРјРµСЂ, ``"replacement"``).
        limit : int
            Максимальное количество примеров.

        Returns
        -------
        list[dict]
        """
        result = list(self._seed_examples)
        if category is not None:
            result = [e for e in result if e.get('category') == category]
        if subcategory is not None:
            result = [e for e in result if e.get('subcategory') == subcategory]
        result.sort(key=lambda e: e.get('id', ''))
        return result[:limit]

    def get_training_context_for_highlights(self, max_examples=5):
        """Сформировать блок текста с характерными примерами подсветки для промпта 4."""
        examples = self.get_seed_examples(category='highlights', limit=max_examples)
        if not examples:
            return ""
        lines = [
            "",
            "# TRAINING_EXAMPLES (Characteristic highlight patterns вЂ” learn from these)",
            "",
            "These examples show CORRECT highlight structures for common change types.",
            "Study the pattern: replacements в†’ difference, additions в†’ addition, deletions в†’ deletion.",
            "",
        ]
        for ex in examples:
            lines.append(f"## {ex.get('id', 'example')}")
            lines.append(f"Description: {ex.get('description', '')}")
            lines.append(f"Input HTML: {ex.get('input_html', '')[:200]}")
            lines.append(f"Output HTML: {ex.get('output_html', '')[:200]}")
            lines.append("Correct highlights:")
            lines.append(json.dumps(ex.get('correct_highlights', {}), ensure_ascii=False, indent=2))
            if ex.get('buggy_highlights'):
                lines.append("вќЊ FORBIDDEN output (do NOT produce this):")
                lines.append(json.dumps(ex.get('buggy_highlights', {}), ensure_ascii=False, indent=2))
            lines.append(f"Lesson: {ex.get('lesson', '')}")
            lines.append("")
        return '\n'.join(lines)

    def get_prompt_supplement(self, stage=4):
        """Вернуть дополнение к промпту для конкретного этапа."""
        if stage == 4:
            return self.get_training_context_for_highlights()
        if stage == 3:
            return self.get_training_context_for_structure()
        return ""

    def get_training_context_for_structure(self, max_examples=5):
        """РЎС„РѕСЂРјРёСЂРѕРІР°С‚СЊ Р±Р»РѕРє С‚РµРєСЃС‚Р° СЃ С…Р°СЂР°РєС‚РµСЂРЅС‹РјРё РїСЂРёРјРµСЂР°РјРё СЃС‚СЂСѓРєС‚СѓСЂРЅС‹С… РїР°С‚С‚РµСЂРЅРѕРІ РґР»СЏ РїСЂРѕРјРїС‚Р° 3."""
        examples = self.get_seed_examples(category='structure', limit=max_examples)
        if not examples:
            return ""
        lines = [
            "",
            "# TRAINING_EXAMPLES (Characteristic structural patterns вЂ” learn from these)",
            "",
            "These examples show CORRECT handling of characteristic legal amendment patterns.",
            "Study the pattern and apply it when you encounter similar situations.",
            "",
        ]
        for ex in examples:
            lines.append(f"## {ex.get('id', 'example')}")
            lines.append(f"Description: {ex.get('description', '')}")
            if ex.get('input_structure'):
                lines.append(f"Input structure: {json.dumps(ex.get('input_structure'), ensure_ascii=False)[:300]}")
            if ex.get('amending_changes'):
                lines.append(f"Amending changes: {json.dumps(ex.get('amending_changes'), ensure_ascii=False)[:300]}")
            if ex.get('correct_output_structure'):
                lines.append(f"Correct output: {json.dumps(ex.get('correct_output_structure'), ensure_ascii=False)[:300]}")
            if ex.get('buggy_output_structure'):
                lines.append(f"FORBIDDEN output (do NOT produce this): {json.dumps(ex.get('buggy_output_structure'), ensure_ascii=False)[:300]}")
            lines.append(f"Lesson: {ex.get('lesson', '')}")
            lines.append("")
        return '\n'.join(lines)
