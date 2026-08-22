"""E2E regression test: 380-ЗС (04.12.2017) applied to 269-ЗС (28.07.2016).

Covers the final-fix acceptance criteria:

* full pipeline run produces ``verification.passed == True``, 0 errors,
  0 warnings;
* all 11 amendment operations are applied AND verified;
* historical revisions and HTML are preserved byte-for-byte;
* article 4 is structurally correct on every level;
* tree snapshots for 08.08.2016 / 14.12.2017 / 15.12.2017 are distinguishable;
* idempotency: re-running the pipeline with the same inputs produces the same
  semantic JSON.
"""

import json
import os

import pytest

from npa_processor.learning.verifier import StructureVerifier
from npa_processor.processing.revision_tree_sync import get_effective_revision

WORK_SOURCE = os.path.join(os.path.dirname(__file__), "..", "work", "source")


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _walk_all(items):
    for item in items:
        yield item
        yield from _walk_all(item.get("item_children", []))


def _find_item(data, item_id):
    for item in _walk_all(data.get("npa_items_revision", [])):
        if item.get("item_id") == item_id:
            return item
    return None


def _norm_body(body):
    return [
        (block.get("type"), block.get("item_id"), block.get("html_text"))
        for block in body
    ]


def _run_pipeline(tmp_path, source_path, target_path):
    """Запуск полного pipeline с redirected report/history артефактами."""
    import scripts.run_pipeline as pipeline

    history_dir = str(tmp_path / "history")
    os.makedirs(history_dir, exist_ok=True)

    old_report = pipeline.REPORT_PATH
    old_learning = pipeline.LEARNING_DIR
    pipeline.REPORT_PATH = str(tmp_path / "report.md")
    pipeline.LEARNING_DIR = history_dir
    try:
        pipeline.main([
            "--source", source_path,
            "--target", target_path,
            "--result-dir", str(tmp_path),
        ])
    finally:
        pipeline.REPORT_PATH = old_report
        pipeline.LEARNING_DIR = old_learning

    fname = "269_2016_07_27_izm_380_2017_12_04.json"
    result_path = os.path.join(str(tmp_path), fname)
    report_path = os.path.join(str(tmp_path), fname.replace(".json", "_report.json"))
    return _load_json(result_path), _load_json(report_path)


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    """Запускает pipeline один раз на модуль и возвращает результат + report."""
    tmp = tmp_path_factory.mktemp("e2e_380_269")
    source = os.path.join(WORK_SOURCE, "380.json")
    target = os.path.join(WORK_SOURCE, "269.json")
    result, report = _run_pipeline(tmp, source, target)
    return {
        "result": result,
        "report": report,
        "target_before": _load_json(target),
        "tmp": tmp,
        "source": source,
        "target": target,
    }


def test_e2e_full_pipeline_verification_and_history(e2e):
    """Полный verifier: 0 ошибок/предупреждений, 11/11 применено и проверено."""
    result = e2e["result"]
    report = e2e["report"]

    verifier = StructureVerifier()
    verification = verifier.verify(result)
    assert verification.passed is True
    assert report["verification"]["passed"] is True
    assert report["verification"]["total_errors"] == 0
    assert report["verification"]["total_warnings"] == 0
    assert report["verification"]["changes_total"] == 11
    assert report["verification"]["changes_passed"] == 11
    assert report["verification"]["changes_failed"] == 0


def test_e2e_old_html_and_head_preserved(e2e):
    """Старые редакции и старый заголовок сохраняются байт-в-байт."""
    result = e2e["result"]
    target_before = e2e["target_before"]

    for item in _walk_all(target_before.get("npa_items_revision", [])):
        res_item = _find_item(result, item["item_id"])
        assert res_item is not None, f"исторический элемент потерян: {item['item_id']}"
        old_rev = None
        for rev in res_item.get("revisions", []):
            if rev.get("valid_from") == "08.08.2016":
                old_rev = rev
                break
        if old_rev is None:
            continue  # элемент создан только новой редакцией
        tgt_body = item["revisions"][0].get("body", [])
        assert _norm_body(old_rev.get("body", [])) == _norm_body(tgt_body), (
            f"старый HTML изменён для {item['item_id']}"
        )

    assert result["head_revision"][0]["npa_head"] == \
        target_before["head_revision"][0]["npa_head"]
    assert any(h.get("valid_from") == "15.12.2017" for h in result["head_revision"])


def test_e2e_article_4_all_levels(e2e):
    """Статья 4 структурно корректна на всех уровнях (article -> part -> point)."""
    result = e2e["result"]
    art4 = _find_item(result, "16012_article_4")
    assert art4 is not None and art4["item_type"] == "article"

    old4 = [r for r in art4["revisions"] if r.get("valid_from") == "08.08.2016"]
    new4 = [r for r in art4["revisions"] if r.get("valid_from") == "15.12.2017"]
    assert len(old4) == 1 and len(new4) == 1
    assert old4[0].get("valid_to") == "14.12.2017"
    assert new4[0].get("valid_to") is None

    old_refs = [b["item_id"] for b in old4[0]["body"] if b["type"] == "child_ref"]
    new_refs = [b["item_id"] for b in new4[0]["body"] if b["type"] == "child_ref"]
    assert old_refs == [
        "16012_article_4_point_1",
        "16012_article_4_point_2",
        "16012_article_4_point_3",
        "16012_article_4_point_4",
        "16012_article_4_point_5",
    ]
    assert new_refs == ["16012_article_4_part_1", "16012_article_4_part_2"]

    part1 = _find_item(result, "16012_article_4_part_1")
    assert part1 is not None and part1["item_type"] == "part"
    assert part1["item_level"] == 2
    eff = get_effective_revision(part1, "15.12.2017")
    assert eff is not None and eff["valid_from"] == "15.12.2017"
    assert get_effective_revision(part1, "14.12.2017") is None

    expected_points = [f"16012_article_4_part_1_point_{n}" for n in range(1, 6)]
    assert [c["item_id"] for c in part1["item_children"]] == expected_points
    for pid in expected_points:
        point = _find_item(result, pid)
        assert point["item_type"] == "point"
        assert point["item_level"] == 3
        assert get_effective_revision(point, "15.12.2017")["valid_from"] == "15.12.2017"

    # Исторический пункт статьи активен только до 14.12.2017 включительно.
    old_point = _find_item(result, "16012_article_4_point_1")
    assert get_effective_revision(old_point, "14.12.2017")["valid_from"] == "08.08.2016"
    assert get_effective_revision(old_point, "15.12.2017") is None


def test_e2e_tree_snapshots(e2e):
    """Дерево по датам: 14.12.2017 — старая редакция, 15.12.2017 — новая."""
    result = e2e["result"]
    article_1 = _find_item(result, "16012_article_1")
    assert get_effective_revision(article_1, "14.12.2017").get("mod_type") is None
    assert get_effective_revision(article_1, "15.12.2017").get("mod_type") == "new_redaction"
    # граничные даты
    assert get_effective_revision(article_1, "08.08.2016")["valid_from"] == "08.08.2016"
    assert get_effective_revision(article_1, "07.08.2016") is None


def test_e2e_all_11_changes(e2e):
    """Каждое из 11 изменений применено, попало в дерево и получило корректные
    временные/метаданные атрибуты."""
    result = e2e["result"]

    # (item_id|None=заголовок, mod_type, expected_modified_by_id)
    cases = [
        (None, "new_redaction", "33699_article_1_point_1"),      # Наименование
        ("16012_article_1", "new_redaction", "33699_article_1_point_2"),
        ("16012_article_2", "new_redaction", "33699_article_1_point_3"),
        ("16012_article_3", "new_redaction", "33699_article_1_point_4"),
        ("16012_article_4", "new_redaction", "33699_article_1_point_5"),
        ("16012_article_5", "new_redaction", "33699_article_1_point_6"),
        ("16012_article_5_1", "add", "33699_article_1_point_7"),
        ("16012_article_5_2", "add", "33699_article_1_point_7"),
        ("16012_article_6", "new_redaction", "33699_article_1_point_8"),
        ("16012_article_7", "new_redaction", "33699_article_1_point_9"),
        ("16012_article_8", "new_redaction", "33699_article_1_point_10"),
    ]
    for item_id, mod_type, expected_by in cases:
        if item_id is None:
            revs = result["head_revision"]
        else:
            item = _find_item(result, item_id)
            assert item is not None, f"изменение {item_id} не попало в дерево"
            revs = item["revisions"]
        new_revs = [r for r in revs if r.get("valid_from") == "15.12.2017"]
        assert len(new_revs) >= 1, f"нет ревизии 15.12.2017 у {item_id}"
        target_rev = new_revs[-1]
        assert target_rev.get("mod_type") == mod_type, f"mod_type у {item_id}"
        assert target_rev.get("modified_by_id") == expected_by, (
            f"modified_by_id у {item_id}"
        )
        assert target_rev.get("valid_to") is None


def test_e2e_added_articles_children_correct(e2e):
    """Пункты статей 5.1/5.2 появляются с датой 15.12.2017 (не 08.08.2016)."""
    result = e2e["result"]
    for article_id, n_points in (
        ("16012_article_5_1", 2),
        ("16012_article_5_2", 5),
    ):
        article = _find_item(result, article_id)
        assert article is not None
        points = [c.get("item_id") for c in article.get("item_children", [])]
        assert len(points) == n_points
        for pid in points:
            point = _find_item(result, pid)
            assert point.get("item_type") == "point"
            eff = get_effective_revision(point, "15.12.2017")
            assert eff is not None, f"нет effective revision на 15.12.2017 у {pid}"
            assert eff.get("valid_from") == "15.12.2017"
            assert eff.get("mod_type") == "add"


def test_e2e_recursion_depth_article_part_point_subpoint(e2e):
    """Глубина article -> part -> point -> subpoint обработана рекурсивно.

    В качестве реального рекурсивного случая берём статью 4: дерево
    article -> part_1 -> point -> (subpoints отсутствуют), и дополнительно
    проверяем, что материализация дерева не создаёт «плоскостных» дублей.
    """
    result = e2e["result"]
    part1 = _find_item(result, "16012_article_4_part_1")
    for child in part1.get("item_children", []):
        if child.get("item_type") == "point":
            assert child.get("item_level") == 3
            eff = get_effective_revision(child, "15.12.2017")
            assert eff is not None and eff["valid_from"] == "15.12.2017"
    # В каждой вершине не более одной открытой ревизии (нет duplicates).
    # Исторически удалённые элементы могут иметь 0 открытых ревизий.
    for item in _walk_all(result.get("npa_items_revision", [])):
        open_revs = [r for r in item.get("revisions", []) if r.get("valid_to") is None]
        assert len(open_revs) <= 1, f"дубли открытых ревизий у {item['item_id']}"


def test_e2e_stage_counters_documented(e2e):
    """Числа этапов pipeline для сценария 380→269 зафиксированы и объяснены:

    * Stage 1 (утрата силы)  = 0: в work/answers нет prompt_1_answer.json —
      380-ЗС ничего не отменяет;
    * Stage 2 (даты)         = 0: нет prompt_2_answer.json — ретроактивных
      указаний нет;
    * Stage 4 (HTML-обработка) = 0: этап обрабатывает только изменения типа
      ``change`` (их в 380-ЗС нет; new_redaction/add проходят через Stage 5);
    * Stage 5 (rebuild)      = 10: 8 статей с new_redaction (№№ 1–8, включая
      статью 4) + 2 новые статьи 5.1/5.2 (add).
    """
    report = e2e["report"]
    assert report["stage1"] == {"found": 0, "applied": 0, "failed": 0}
    assert report["stage2"] == {"found": 0, "applied": 0, "failed": 0}
    assert report["stage3"]["found"] == 11
    assert report["stage3"]["applied"] == 11
    assert report["stage3"]["failed"] == 0
    assert report["stage4"] == {"processed": 0}
    assert report["stage5"] == {"rebuild_count": 10}


def test_e2e_idempotency(e2e):
    """Повторный прогон pipeline с теми же входами даёт тот же семантический JSON
    (без duplicate revisions и без изменения данных «на всякий случай»)."""
    result, report = _run_pipeline(e2e["tmp"] / "run2", e2e["source"], e2e["target"])
    assert result == e2e["result"]
    assert report["verification"]["passed"] is True
