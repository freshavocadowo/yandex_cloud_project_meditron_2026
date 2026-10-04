"""Промпт и JSON-схема ответа для LLM-извлечения. Версия меняется при любой правке текста."""
from ..schema import DESCRIPTIONS, ENUMS, NOT_FOUND, check_value

PROMPT_VERSION = "1"

SYSTEM = f"""Ты извлекаешь признаки из синтетического кардиологического выписного эпикриза (ОКС).
Правила записи:
- Даты — ДД.ММ.ГГГГ без времени. Числа — без единиц измерения, десятичная точка. Давление — 140/90.
- Если значение не найдено, пиши «{NOT_FOUND}». Не вычисляй показатели, которых нет в тексте (например, ИМТ).
- Бинарные коды: 1 — прямое указание признака, 0 — явное отрицание или отсутствие упоминания.
- Лабораторные показатели — первый результат госпитализации; АД и пульс — первичный осмотр; ЭКГ — запись ЭКГ.
- Коронарография: Y выполнена, R документирован отказ, N сведений нет. Сосуды 0/1/2 только при выполненной КАГ:
  0 — стеноз менее 50%, 1 — 50–89%, 2 — 90% и более или окклюзия.
- Препараты — назначения при выписке, строкой как в тексте (название, доза, режим).
Для каждого поля верни value и evidence — точную цитату из текста (5–150 символов), на которой основано значение.
Если значение «{NOT_FOUND}» или 0 по отсутствию упоминания, evidence — пустая строка.
Отвечай только JSON по схеме."""


def user_prompt(text: str, fields: list[str]) -> str:
    lines = "\n".join(f"- {key}: {DESCRIPTIONS[key]}" for key in fields)
    return f"Поля:\n{lines}\n\nЭпикриз:\n<<<\n{text}\n>>>"


def response_schema(fields: list[str]) -> dict:
    def value_schema(key: str) -> dict:
        if key in ENUMS:
            allowed = ENUMS[key] | ({NOT_FOUND} if check_value(key, NOT_FOUND) is None else set())
            return {"type": "string", "enum": sorted(allowed)}
        return {"type": "string"}

    item = lambda key: {"type": "object", "additionalProperties": False, "required": ["value", "evidence"],
                        "properties": {"value": value_schema(key), "evidence": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": list(fields),
            "properties": {key: item(key) for key in fields}}


def repair_prompt(errors: list[str]) -> str:
    return "Ответ не прошёл проверку: " + "; ".join(errors) + ". Исправь и верни JSON целиком."
