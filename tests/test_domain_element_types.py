from npa_processor.constants import TYPE_TO_RUSSIAN as legacy_type_names
from npa_processor.domain.element_types import TYPE_TO_RUSSIAN, normalize_ru_type


def test_type_vocabulary_has_expected_canonical_types():
    assert TYPE_TO_RUSSIAN["article"] == "Статья"
    assert TYPE_TO_RUSSIAN["structured_table"] == "Таблица"


def test_constants_module_reexports_canonical_mapping():
    assert legacy_type_names is TYPE_TO_RUSSIAN


def test_russian_inflections_normalize_to_one_type():
    assert normalize_ru_type("статья") == "статья"
    assert normalize_ru_type("статьи") == "статья"
    assert normalize_ru_type("статью") == "статья"
    assert normalize_ru_type("пункты") == "пункт"
    assert normalize_ru_type("пункта") == "пункт"
    assert normalize_ru_type("приложения") == "приложение"
