# Отчёт об обработке НПА

## Исходные данные
- Изменяющий НПA: 380-ЗС от 04.12.2017 (valid_from: 15.12.2017)
- Целевой НПA: 269-ЗС от 28.07.2016 (valid_from: 08.08.2016)

## Этап 1: Утрата силы
- Найдено указаний: 0
- Применено: 0
- Ошибки: 0

## Этап 2: Даты и ретроактивность
- Найдено указаний: 0
- Применено: 0
- Ошибки: 0

## Этап 3: Изменения
- Найдено изменений: 11
  - add: 2
  - delete: 0
  - change: 0
  - new_redaction: 9
- Применено: 11
- Не применено: 0
- Ошибок верификации: 10
- Предупреждений: 0

### Применённые изменения
1. Наименование [new_redaction] — успешно
2. Статья 1 [new_redaction] — успешно
3. Статья 2 [new_redaction] — успешно
4. Статья 3 [new_redaction] — успешно
5. Статья 4 [new_redaction] — успешно
6. Статья 5 [new_redaction] — успешно
7. нпа [add] — успешно
8. нпа [add] — успешно
9. Статья 6 [new_redaction] — успешно
10. Статья 7 [new_redaction] — успешно
11. Статья 8 [new_redaction] — успешно
- Список ошибок:
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_4_part_1' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_4' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_4_part_2' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_4' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_5_1_point_1' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_5_1' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_5_1_point_2' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_5_1' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_5_2_point_1' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_5_2' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_5_2_point_2' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_5_2' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_5_2_point_3' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_5_2' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_5_2_point_4' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_5_2' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_5_2_point_5' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_5_2' от '15.12.2017'
  - VERIFY[stale_child_revision]: Ребёнок '16012_article_7_part_7' имеет последнюю ревизию от '08.08.2016', которая старше ревизии родителя '16012_article_7' от '15.12.2017'

## Этап 4: HTML-обработка
- Обработано элементов: 0

## Этап 5: Перестройка
- Элементов на перестройку: 10
    - История документа сохранена в: learning/history/20260822_123550_434045/

## Верификация структуры (самообучение)
- Статус: С ОШИБКАМИ
- Изменений проверено: 11
- Изменений прошло проверку: 11
- Изменений не прошло проверку: 0

## Исправления багов (агент)
- Применено автоматических исправлений: 3
### revision_valid_from_missing
- Установлен valid_from='15.12.2017' для 76 элементов
- Затронуто: 16012_article_1, 16012_article_2, 16012_article_2_part_1, 16012_article_2_part_1_point_1, 16012_article_2_part_1_point_2, 16012_article_2_part_1_point_3, 16012_article_2_part_1_point_4, 16012_article_2_part_2, 16012_article_3, 16012_article_3_point_1
  - 16012_article_1: before=None → after=08.08.2016
  - 16012_article_2: before=None → after=08.08.2016
  - 16012_article_2_part_1: before=None → after=08.08.2016
  - 16012_article_2_part_1_point_1: before=None → after=08.08.2016
  - 16012_article_2_part_1_point_2: before=None → after=08.08.2016
  - 16012_article_2_part_1_point_3: before=None → after=08.08.2016
  - 16012_article_2_part_1_point_4: before=None → after=08.08.2016
  - 16012_article_2_part_2: before=None → after=08.08.2016
  - 16012_article_3: before=None → after=08.08.2016
  - 16012_article_3_point_1: before=None → after=08.08.2016
### child_ref_broken
- Удалены битые child_ref, ссылающиеся на несуществующие item_id (5 шт.)
- Затронуто: 16012_article_4_point_1, 16012_article_4_point_2, 16012_article_4_point_3, 16012_article_4_point_4, 16012_article_4_point_5
  - Родитель: 16012_article_4 (article 4)
    Удалён битый child_ref: 16012_article_4_point_1
  - Родитель: 16012_article_4 (article 4)
    Удалён битый child_ref: 16012_article_4_point_2
  - Родитель: 16012_article_4 (article 4)
    Удалён битый child_ref: 16012_article_4_point_3
  - Родитель: 16012_article_4 (article 4)
    Удалён битый child_ref: 16012_article_4_point_4
  - Родитель: 16012_article_4 (article 4)
    Удалён битый child_ref: 16012_article_4_point_5
### item_level_invalid
- Пересчитан item_level для 2 элементов
- Затронуто: 16012_article_5_1, 16012_article_5_2
  - 16012_article_5_1: article 5.1 — before=2 → after=1
  - 16012_article_5_2: article 5.2 — before=2 → after=1

## Характерные примеры ошибок (последние 10)
- Всего зафиксировано примеров: 10
 - [stale_child_revision] None: Ребёнок '16012_article_7_part_7' имеет последнюю ревизию от '08.08.2016', которая старше ревизии род
 - [stale_child_revision] None: Ребёнок '16012_article_5_2_point_5' имеет последнюю ревизию от '08.08.2016', которая старше ревизии 
 - [stale_child_revision] None: Ребёнок '16012_article_5_2_point_4' имеет последнюю ревизию от '08.08.2016', которая старше ревизии 
 - [stale_child_revision] None: Ребёнок '16012_article_5_2_point_3' имеет последнюю ревизию от '08.08.2016', которая старше ревизии 
 - [stale_child_revision] None: Ребёнок '16012_article_5_2_point_2' имеет последнюю ревизию от '08.08.2016', которая старше ревизии 
 - [stale_child_revision] None: Ребёнок '16012_article_5_2_point_1' имеет последнюю ревизию от '08.08.2016', которая старше ревизии 
 - [stale_child_revision] None: Ребёнок '16012_article_5_1_point_2' имеет последнюю ревизию от '08.08.2016', которая старше ревизии 
 - [stale_child_revision] None: Ребёнок '16012_article_5_1_point_1' имеет последнюю ревизию от '08.08.2016', которая старше ревизии 
 - [stale_child_revision] None: Ребёнок '16012_article_4_part_2' имеет последнюю ревизию от '08.08.2016', которая старше ревизии род
 - [stale_child_revision] None: Ребёнок '16012_article_4_part_1' имеет последнюю ревизию от '08.08.2016', которая старше ревизии род

## Итог
- Статус: С ошибками
- Итоговый файл: work/results/269_2016_07_27_izm_380_2017_12_04.json
- Время выполнения: 0.2с
