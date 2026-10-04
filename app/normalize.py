"""Приведение найденных значений к единым правилам записи из ТЗ.

Даты — ДД.ММ.ГГГГ без времени; числа — без единиц, десятичная точка;
давление — верхнее/нижнее; римские классы — арабскими цифрами.
"""
import re

MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8,
          "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
MONTH_RE = r"(?:январ|феврал|марта?|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*"
# Дата в тексте: 10.09.2021, 10/09/21, 10-09-2021, «10 сентября 2021 г.»
DATE_RE = rf"\d{{1,2}}[./-]\d{{1,2}}[./-](?:\d{{4}}|\d{{2}})(?!\d)|\d{{1,2}}\s+{MONTH_RE}\s+\d{{4}}"
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}


def date(raw: str) -> str | None:
    raw = raw.strip()
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})", raw)
    if m:
        day, month, year = int(m[1]), int(m[2]), m[3]
    else:
        m = re.fullmatch(rf"(\d{{1,2}})\s+({MONTH_RE})\s+(\d{{4}})", raw, re.IGNORECASE)
        if not m:
            return None
        stem = next(s for s in sorted(MONTHS, key=len, reverse=True) if m[2].lower().startswith(s))
        day, month, year = int(m[1]), MONTHS[stem], m[3]
    if len(year) == 2:
        year = "20" + year
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return f"{day:02d}.{month:02d}.{year}"


def number(raw: str) -> str:
    """«27,4» -> «27.4»; лишние пробелы-разделители разрядов убираются."""
    return re.sub(r"\s+", "", raw).replace(",", ".")


def arabic(raw: str) -> str:
    raw = raw.strip().upper().replace("І", "I")
    return str(ROMAN[raw]) if raw in ROMAN else raw


def phrase(raw: str) -> str:
    """Текстовое значение: без лишних пробелов и завершающей точки/запятой, с заглавной буквы."""
    text = re.sub(r"\s+", " ", raw).strip(" \t.,;:—–-")
    if text.endswith(" ст"):  # «Митральная регургитация 2 ст.» — точка сокращения часть значения
        text += "."
    return text[:1].upper() + text[1:]


def stenosis_grade(percent: int) -> str:
    """Шкала КАГ: 0 — менее 50%, 1 — 50–89%, 2 — 90% и более."""
    return "0" if percent < 50 else "1" if percent < 90 else "2"
