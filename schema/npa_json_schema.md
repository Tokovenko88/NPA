# СТРУКТУРА JSON НПА (Версия для AI-агента слияния)

## 1. Корневой объект

```json
{
  "npa_id": 123,
  "npa_type": "law",
  "npa_number": "123-ЗС",
  "npa_author": "Законодательное Собрание города Севастополя",
  "npa_url": "https://sevzakon.ru/laws/123-ZS",
  "date_reg": "01.01.2023",
  "date_pub": "20.06.2023",
  "valid_from": "01.07.2023",
  "npa_signer_post": "Председатель",
  "npa_signer": "А.А. Петров",
  "date_format": 1,
  "head_revision": [],
  "revision_info": [],
  "npa_items_revision": []
}
```

### Ключевые поля корня:
- `npa_id` - уникальный числовой ID
- `npa_type` - "law" (закон) или "regulation" (постановление)
- `npa_number` - официальный номер
- `date_pub` - дата публикации (d.m.Y)
- `valid_from` - дата вступления в силу (d.m.Y)
- `head_revision` - история наименований НПА
- `npa_items_revision` - массив верхнеуровневых элементов

## 2. Структурный элемент (item)

```json
{
  "item_id": "123_article_1",
  "item_type": "article",
  "item_number": "1",
  "item_level": 1,
  "head_revisions": [],
  "item_children": [],
  "number_revisions": [],
  "item_prefix_revisions": [],
  "revisions": []
}
```

### Допустимые item_type:
- `preamble` - преамбула
- `chapter` - глава
- `section` - раздел
- `article` - статья
- `part` - часть
- `point` - пункт
- `subpoint` - подпункт
- `appendix` - приложение
- `nested_appendix` - вложенное приложение
- `structured_table` - структурированная таблица

### item_id:
Формат: `<npa_id>_<type>_<number>[_double_N]`
Примеры: `123_article_1`, `123_appendix_2_double_1`

## 3. Ревизии (история редакций)

### 3.1 head_revision (наименование)
```json
{
  "npa_head": "Текст наименования",
  "modified_by_id": "456",
  "valid_from": "01.01.2024",
  "valid_to": null,
  "highlights": {}
}
```

### 3.2 revisions (контент элемента)
```json
{
  "valid_from": "01.01.2024",
  "valid_to": null,
  "modified_by_id": "456",
  "mod_type": "new_redaction",
  "body": [
    {
      "type": "paragraph",
      "html_text": "<p>Текст абзаца</p>",
      "order": 1
    },
    {
      "type": "table",
      "html_text": "<table>...</table>",
      "order": 2
    },
    {
      "type": "child_ref",
      "item_id": "123_point_1",
      "order": 3
    }
  ],
  "highlights": {}
}
```

### 3.3 item_prefix_revisions (префикс приложения)
```json
{
  "prefix_text": "Приложение 1",
  "valid_from": "01.01.2024",
  "valid_to": null,
  "mod_type": "new_redaction",
  "modified_by_id": "456"
}
```

### 3.4 number_revisions (история номеров)
```json
{
  "number_text": "5",
  "valid_from": "01.01.2023",
  "valid_to": "14.03.2025",
  "mod_type": "correction",
  "modified_by_id": "456"
}
```

## 4. Типы изменений (mod_type)

- `new_redaction` - новая редакция (полная замена)
- `add` - добавление
- `delete` - удаление
- `change` - частичное изменение
- `correction` - исправление номера
- `renumber` - перенумерация
- `editorial` - редакционная правка

## 5. Highlights (подсветка изменений)

### Текстовый режим:
```json
{
  "previous_edition": {
    "deletion": [{"text": "старое", "positions": "1-1"}],
    "difference": [{"text": "старое", "positions": "1-2"}]
  },
  "current_edition": {
    "addition": [{"text": "новое", "positions": "1-1"}],
    "difference": [{"text": "новое", "positions": "1-2"}]
  }
}
```

### Табличный режим:
```json
{
  "previous_edition": {
    "deletion": [],
    "difference": [{"text": "table", "positions": "2"}]
  },
  "current_edition": {
    "addition": [],
    "difference": [{"text": "table", "positions": "2"}]
  }
}
```

## 6. Правила работы с ревизиями

### Применение нового изменения:
1. Найти активную ревизию (`valid_to` = null)
2. Если нет активной - взять последнюю
3. Установить `valid_to` = (дата_новой_ревизии - 1 день)
4. Создать новую ревизию с `valid_from` = дата_новой_ревизии
5. Для `new_redaction`/`delete`/`add` - заполнить `body` или `mod_type`
6. Для `change` - изменить `body` существующей ревизии ИЛИ создать новую

### Важные правила:
- `valid_to` всегда = `valid_from` - 1 день (кроме утраты силы всего закона)
- `modified_by_id` - ID изменяющего НПА
- `highlights` заполняется только для изменений, требующих подсветки
- Для `delete` тип `mod_type` = "delete", `body` может быть пустым или содержать старое содержимое

## 7. Элементы с особыми правилами

### 7.1 Наименование элемента (head_revisions)
У статей, глав, разделов, приложений может быть поле `head_revisions`:
```json
{
  "head_text": "Статья 1. Общие положения",
  "valid_from": "01.01.2024",
  "valid_to": null,
  "mod_type": "new_redaction",
  "modified_by_id": "456",
  "highlights": {}
}
```

### 7.2 Префикс приложения
У приложений может быть `item_prefix_revisions`:
```json
{
  "prefix_text": "Приложение 1",
  "valid_from": "01.01.2024",
  "valid_to": null,
  "mod_type": "new_redaction",
  "modified_by_id": "456"
}
```

## 8. Дочерние элементы

```json
{
  "item_children": [
    {
      "item_id": "123_part_1",
      "item_type": "part",
      "item_number": "1",
      "item_level": 2,
      ...
    }
  ]
}
```

В `body` родительского элемента должен быть блок `child_ref`:
```json
{
  "type": "child_ref",
  "item_id": "123_part_1",
  "order": 2
}
```

## 3.5 ЗАПРЕТ: Номера структурных элементов в body paragraphs

**КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** включать номер структурного элемента (`item_number`) в текст `html_text` абзацев (`paragraph`) для элементов типов `part`, `point`, `subpoint`.

- Номер элемента хранится ТОЛЬКО в поле `item_number` на уровне самого элемента.
- В `body[].html_text` абзацы должны содержать ТОЛЬКО текст абзаца без ведущего номера.
- Пример **НЕВЕРНО**: `"html_text": "<p>1. К отдельным категориям граждан...</p>"` у элемента `part` с `item_number: "1"`.
- Пример **ВЕРНО**: `"html_text": "<p>К отдельным категориям граждан...</p>"` у того же элемента.
- Нумерация добавляется только при отображении/рендеринге документа, но НИКОГДА не сохраняется в `html_text` внутри JSON.
