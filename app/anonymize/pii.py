"""Обезличивание: ФИО, дата рождения, возраст, номера документов, контакты.

Найденные фрагменты заменяются токенами ([ФИО], [ДР], ...). Исходные значения
нигде не сохраняются: в Span только тип и позиция токена в обезличенном тексте.
Даты госпитализации, исследований и номера отделений не трогаются — они нужны
для извлечения признаков.
"""
from dataclasses import dataclass, field
import re

TOKENS = {"fio": "[ФИО]", "dob": "[ДР]", "age": "[ВОЗРАСТ]", "id": "[ID]", "phone": "[ТЕЛЕФОН]",
          "email": "[EMAIL]", "snils": "[СНИЛС]", "policy": "[ПОЛИС]", "address": "[АДРЕС]"}

DATE = r"\d{1,2}[./]\d{1,2}[./]\d{2,4}"
WORD = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
# Частицы: «Васко даГамович», «Отто фон Бисмарк», «Ильхам Мамед оглы».
LOOSE_WORD = rf"(?:(?:да|де|ди|дю|ла|ле|фон|ван|ибн|бен|аль|эль)[ \t-]?)?{WORD}"
NAME = rf"{LOOSE_WORD}(?:[ \t]+{LOOSE_WORD}){{0,3}}(?:[ \t]+(?:оглы|кызы))?"
INITIALS = r"[А-ЯЁ]\.[ \t]?[А-ЯЁ]\."
LABEL = r"(?i:ф\.?[ \t]?и\.?[ \t]?о\.?|пациент(?:ка)?|больн(?:ой|ая)|пациент[ \t]?\(ка\))"
DOB_MARK = r"(?i:д\.[ \t]?р\.|дата[ \t]+рождения|родил(?:ся|ась))"
YEARS = r"\d{1,3}[ \t]*(?:год|года|лет)\b"

PATIENT_LABEL = re.compile(rf"\b{LABEL}[ \t]*:[ \t]*$")

# Каждая именованная группа — тип маскируемого фрагмента.
PATTERNS = [re.compile(p) for p in (
    rf"\b{LABEL}[ \t]*:[ \t]*(?P<fio>{NAME})",
    rf"(?i:лечащий[ \t]+врач|зав(?:едующий|\.)[ \t]*отделением|врач)[ \t]*:?[ \t]*(?P<fio>{WORD}(?:[ \t]+{INITIALS}|(?:[ \t]+{WORD}){{1,2}}))",
    rf"(?P<fio>{WORD}[ \t]+{INITIALS})",
    rf"{DOB_MARK}[ \t]*:?[ \t]*(?P<dob>{DATE}|\d{{4}})",
    rf"(?P<dob>\d{{4}})[ \t]*(?i:г\.[ \t]?р\.)",
    rf"{DOB_MARK}[ \t]*:?[ \t]*{DATE}[ \t]*[,;][ \t]*(?:(?i:возраст)[ \t]*:?[ \t]*)?(?P<age>{YEARS})",
    rf"(?i:возраст(?:е)?[ \t]*:?[ \t]*)(?P<age>\d{{1,3}}(?:[ \t]*(?:год|года|лет)\b)?)",
    rf"(?i:истори[яи][ \t]+болезни|медицинская[ \t]+карта|карта[ \t]+стационарного[ \t]+больного)[ \t]*(?:№|N|#)[ \t]*(?P<id>[\w/-]+)",
    rf"№[ \t]*(?i:истории[ \t]+болезни|медицинской[ \t]+карты)[ \t]*:?[ \t]*(?P<id>[\w/-]+)",
    r"(?P<phone>(?:\+7|\b8)[ \t(-]*\d{3}[ \t)-]*\d{3}[ \t-]*\d{2}[ \t-]*\d{2}\b)",
    r"(?P<email>[\w.+-]+@[\w-]+\.[\w.-]+)",
    r"(?P<snils>\b\d{3}-\d{3}-\d{3}[ -]\d{2}\b)",
    r"(?i:полис(?:[ \t]+омс)?|омс)[ \t]*№?[ \t]*:?[ \t]*(?P<policy>\d[\d ]{9,18}\d)",
    r"(?i:адрес(?:[ \t]+проживания)?|место[ \t]+жительства|проживает)[ \t]*:[ \t]*(?P<address>[^\n]+)",
)]
# Хвост строки пациента после ФИО — до сведений о госпитализации.
PATIENT_TAIL = re.compile(r"[^\n]*?(?=(?i:период[ \t]+лечения|поступил|госпитализ|дата[ \t]+поступления|выписан)|\n|$)")
TAIL_ITEMS = re.compile(rf"(?P<dob>{DATE}|\b\d{{3,4}}(?=[ \t]*(?:г\.|года?\b)))|(?P<age>{YEARS})")
# После метки пациента должен стоять токен, иначе имя не распознано шаблоном NAME.
UNMASKED_LABEL = re.compile(rf"\b{LABEL}[ \t]*:[ \t]*(?!\[ФИО\])[^\W\d_]")
VOWEL_END = re.compile(r"[аяеоийыьу]{1,2}$")


@dataclass(frozen=True)
class Span:
    kind: str
    start: int  # позиция токена в обезличенном тексте
    end: int


@dataclass
class Anonymized:
    text: str
    spans: list[Span] = field(default_factory=list)
    residual: list[str] = field(default_factory=list)  # типы ПДн, найденные после маскирования


def _name_variants(words: set[str]) -> re.Pattern | None:
    """Падежные формы имени и фамилии: Орлеанская -> Орлеанской, Бисмарков -> Бисмаркову."""
    stems = {VOWEL_END.sub("", w) for w in words}
    # Короткие основы (Перв-, Мар-) совпадают с обычными словами: «Первые сутки».
    stems = sorted((s for s in stems if len(s) >= 5), key=len, reverse=True)
    if not stems:
        return None
    return re.compile(rf"\b(?:{'|'.join(map(re.escape, stems))})[а-яё]{{0,3}}\b")


def find_spans(text: str) -> list[tuple[int, int, str]]:
    found = []
    for pattern in PATTERNS:
        for m in pattern.finditer(text):
            for kind, value in m.groupdict().items():
                if value:
                    found.append((m.start(kind), m.end(kind), kind))
    # Нестандартные ДР и возраст в строке пациента: «условная дата 1206 г.; около 814 лет».
    for start, end, kind in list(found):
        if kind == "fio" and PATIENT_LABEL.search(text[max(0, start - 30):start]):
            tail = PATIENT_TAIL.match(text, end)
            for m in TAIL_ITEMS.finditer(text, end, tail.end()):
                kind_ = "dob" if m.group("dob") else "age"
                found.append((m.start(kind_), m.end(kind_), kind_))
    # Повторные упоминания пациента в тексте; отчество отдельно не ищем.
    words = set()
    for start, end, kind in found:
        if kind == "fio":
            parts = text[start:end].split()
            words.update(p for p in parts if "." not in p and not re.search(r"(?:вич|вна|ична|чна)$", p))
    variants = _name_variants(words)
    if variants:
        found += [(m.start(), m.end(), "fio") for m in variants.finditer(text)]
    # Пересечения объединяются; приоритет у более раннего и длинного фрагмента.
    merged: list[tuple[int, int, str]] = []
    for start, end, kind in sorted(found, key=lambda s: (s[0], -s[1])):
        if merged and start < merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), prev[2])
        else:
            merged.append((start, end, kind))
    return merged


def residual_identifiers(text: str) -> list[str]:
    """Проверка обезличенного текста: что осталось похожим на ПДн."""
    kinds = ["fio"] if UNMASKED_LABEL.search(text) else []
    for start, end, kind in find_spans(text):
        if text[start:end] not in TOKENS.values():
            kinds.append(kind)
    return sorted(set(kinds))


def anonymize(text: str) -> Anonymized:
    parts, spans, pos, shift = [], [], 0, 0
    for start, end, kind in find_spans(text):
        token = TOKENS[kind]
        parts.append(text[pos:start])
        new_start = start + shift
        spans.append(Span(kind, new_start, new_start + len(token)))
        parts.append(token)
        shift += len(token) - (end - start)
        pos = end
    parts.append(text[pos:])
    masked = "".join(parts)
    return Anonymized(masked, spans, residual_identifiers(masked))
