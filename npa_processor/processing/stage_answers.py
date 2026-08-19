"""Утилиты для загрузки ответов агента этапа 4."""

import json
import os

from npa_processor.paths import ANSWERS_DIR
from npa_processor.processing.text_utils import strip_thinking_tags

_stage4_usage_counters = {}


def reset_stage4_counters():
    """Сбросить счётчики использования ответов stage 4. Вызывать в начале каждого pipeline-run."""
    global _stage4_usage_counters
    _stage4_usage_counters = {}

def get_stage4_agent_answer(base_key, log_callback=None, index=None):
    if index is None:
        counter = _stage4_usage_counters.get(base_key, 0)
        _stage4_usage_counters[base_key] = counter + 1
    else:
        counter = index

    path = os.path.join(ANSWERS_DIR, f"prompt_4_answer_{base_key}.json")
    if not os.path.exists(path):
        if log_callback:
            log_callback(f"  Ответ агента этапа 4 не найден: prompt_4_answer_{base_key}.json", 'error')
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        if log_callback:
            log_callback(f"  Ошибка чтения ответа агента этапа 4: {e}", 'error')
        return None

    answer = None
    if 'responses' in data:
        responses = data['responses']
        if counter < len(responses):
            answer = responses[counter]
        else:
            if log_callback:
                log_callback(
                    f"  Недостаточно ответов в prompt_4_answer_{base_key}.json "
                    f"(нужен #{counter+1}, есть {len(responses)})",
                    'error'
                )
            return None
    else:
        answer = data.get('response', data.get('answer', ''))

    if not answer:
        return None

    cleaned = strip_thinking_tags(answer)
    return cleaned
