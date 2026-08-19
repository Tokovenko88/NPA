from npa_processor.constants import TYPE_TO_RUSSIAN as legacy_type_names
from npa_processor.domain.element_types import (
    TYPE_TO_RUSSIAN,
    normalize_ru_type,
)


def test_constants_module_keeps_canonical_mapping_alias():
    assert legacy_type_names is TYPE_TO_RUSSIAN


def test_russian_inflections_normalize_to_one_type():
    assert normalize_ru_type("статьи") == "статья"
    assert normalize_ru_type("пункта") == "пункт"
    assert normalize_ru_type("подпункты") == "подпункт"
    assert normalize_ru_type("приложения") == "приложение"


def test_canonical_types_have_russian_labels():
    for item_type in ("article", "part", "point", "subpoint", "chapter", "section"):
        assert item_type in TYPE_TO_RUSSIAN
        assert TYPE_TO_RUSSIAN[item_type]
