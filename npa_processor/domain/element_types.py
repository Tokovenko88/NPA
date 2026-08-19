"""Single source of truth for NPA structural element type names."""

from __future__ import annotations

TYPE_TO_RUSSIAN = {
    "article": "Статья",
    "part": "Часть",
    "point": "Пункт",
    "subpoint": "Подпункт",
    "chapter": "Глава",
    "section": "Раздел",
    "appendix": "Приложение",
    "paragraph": "Абзац",
    "preamble": "Преамбула",
    "structured_table": "Таблица",
}

# All inflected forms normalize to the canonical structural type.
RUSSIAN_TYPE_ALIASES = {
    "статья": "статья", "статьи": "статья", "статью": "статья",
    "часть": "часть", "части": "часть",
    "пункт": "пункт", "пункты": "пункт", "пункта": "пункт",
    "подпункт": "подпункт", "подпункты": "подпункт",
    "абзац": "абзац", "абзацы": "абзац",
    "глава": "глава", "главы": "глава",
    "раздел": "раздел", "разделы": "раздел",
    "приложение": "приложение", "приложения": "приложение",
    "преамбула": "преамбула",
    "таблица": "таблица", "таблицы": "таблица",
}


def normalize_ru_type(value: object) -> str:
    """Normalize a Russian structural element type to its canonical form."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    return RUSSIAN_TYPE_ALIASES.get(text, text)
