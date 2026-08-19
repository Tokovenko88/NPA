TYPE_TO_RUSSIAN = {
    'article': 'Статья',
    'part': 'Часть',
    'point': 'Пункт',
    'subpoint': 'Подпункт',
    'chapter': 'Глава',
    'section': 'Раздел',
    'appendix': 'Приложение',
    'paragraph': 'Абзац',
    'preamble': 'Преамбула',
    'structured_table': 'Таблица',
}

# Морфология русских названий типов живёт в processing/element_ops._ETYPE_WORDS
# TYPE_TO_RUSSIAN — канонические eng keys → русские заголовки
#
# ВАЖНО: при добавлении нового item_type нужно обновить И TYPE_TO_RUSSIAN здесь,
# И _ETYPE_WORDS в npa_processor/processing/element_ops.py (обе таблицы синхронно),
# чтобы новые элементы корректно именовались при генерации структурных путей и заголовков.
