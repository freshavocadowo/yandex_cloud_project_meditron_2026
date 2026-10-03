"""Деление эпикриза на разделы по словарю синонимов заголовков.

Текст не изменяется: start/body_start/end — смещения в исходной строке.
Заголовок распознаётся в начале строки в четырёх формах:
  «ЭКГ» / «ЭКГ:» отдельной строкой; «ЭКГ: текст»; «ЭКГ. Текст»; «Основная жалоба — текст».
"""
from dataclasses import dataclass, field
import re

# kind -> синонимы заголовка (регистр не важен). Порядок не важен: длинные варианты проверяются первыми.
HEADINGS: dict[str, list[str]] = {
    "diagnosis": ["диагноз", "клинический диагноз", "заключительный диагноз", "диагноз при выписке",
                  "основной диагноз", "заключительный клинический диагноз"],
    "history": ["жалобы", "жалобы при поступлении", "жалобы и анамнез заболевания", "анамнез заболевания",
                "анамез заболевания", "из анамнеза", "анамнез", "основная жалоба", "повод для обращения",
                "со слов больного, повод для обращения", "со слов больной, повод для обращения",
                "со слов пациента, повод для обращения", "со слов пациентки, повод для обращения"],
    "life_history": ["анамнез жизни"],
    "exam": ["осмотр при поступлении", "объективно при поступлении", "первичный статус", "данные осмотра",
             "объективно", "объективный статус", "status praesens"],
    "ecg": ["экг", "экг при поступлении", "электрокардиография", "инструментальные данные"],
    "echo": ["эхо-кг", "эхокг", "эхо кг", "эхокардиография", "узи сердца"],
    "xray": ["рентген огк", "рентгенография грудной клетки", "рентгенография огк", "рентгенологические данные",
             "р-графия органов грудной клетки", "рентгенография органов грудной клетки"],
    "ca": ["каг", "коронарография", "коронароангиография", "исследование коронарного русла", "инвазивная диагностика"],
    "labs": ["анализы крови", "лабораторные данные", "лабораторные исследования", "исследования", "анализы"],
    "treatment": ["лечение", "лечение и исход", "проведённое лечение", "проведенное лечение", "терапия в стационаре"],
    "followup": ["состояние в динамике", "данные наблюдения", "контроль в динамике", "повторный осмотр",
                 "контрольные исследования", "течение заболевания", "течение госпитализации", "динамика в стационаре"],
    "consult": ["консультации", "консультативные заключения", "заключения специалистов", "осмотры специалистов"],
    "therapy": ["рекомендации", "рекомендации при выписке", "назначения при выписке", "дальнейшее наблюдение",
                "после выписки назначено", "постоянная терапия при выписке", "рекомендовано продолжить приём",
                "рекомендовано продолжить прием", "рекомедовано продолжить приём", "терапия при выписке"],
    "notes": ["памятка при выписке", "план наблюдения", "порядок амбулаторного контроля", "дополнительно"],
}
# Эти заголовки допустимы только отдельной строкой: «Дополнительно: калий 4,7» — часть анализов.
STANDALONE_ONLY = {"дополнительно", "анализы", "объективно", "анамнез", "жалобы"}

_LOOKUP = {s: kind for kind, synonyms in HEADINGS.items() for s in synonyms}
_ALT = "|".join(re.escape(s).replace(r"\ ", r"\s+") for s in sorted(_LOOKUP, key=len, reverse=True))
HEADING_RE = re.compile(rf"[ \t]*(?:#+[ \t]*)?(?:\*\*)?(?P<h>{_ALT})(?:\*\*)?[ \t]*(?P<sep>:|[—–](?=[ \t])|\.(?=[ \t])|$)",
                        re.IGNORECASE)
CAPS_RE = re.compile(r"[ \t]*(?:#+[ \t]*)?(?P<h>[А-ЯЁA-Z][А-ЯЁA-Z \t,.-]{2,60}?)[ \t]*:?[ \t]*$")
DOC_TITLES = re.compile(r"(?:выписной\s+)?эпикриз|выписка", re.IGNORECASE)


@dataclass(frozen=True)
class Section:
    kind: str
    title: str
    start: int  # начало строки заголовка
    body_start: int  # после заголовка и разделителя
    end: int


@dataclass
class Segmented:
    text: str
    sections: list[Section]
    unknown_headings: list[str] = field(default_factory=list)

    def section_at(self, pos: int) -> Section:
        return next(s for s in self.sections if s.start <= pos < s.end)

    def of(self, kind: str) -> list[Section]:
        return [s for s in self.sections if s.kind == kind]

    def body(self, section: Section) -> str:
        return self.text[section.body_start:section.end]

    def bodies(self, kind: str) -> str:
        return "\n".join(self.body(s) for s in self.of(kind))


def _key(heading: str) -> str:
    return re.sub(r"\s+", " ", heading.lower())


def match_heading(line: str) -> tuple[str, int] | None:
    """(kind, длина заголовка с разделителем) или None."""
    m = HEADING_RE.match(line)
    if m:
        key = _key(m.group("h"))
        standalone = not line[m.end():].strip()
        if standalone or key not in STANDALONE_ONLY:
            return _LOOKUP[key], m.end()
    m = CAPS_RE.match(line)
    if m and sum(c.isalpha() for c in m.group("h")) >= 3:
        # Неизвестный заголовок капсом: отдельный раздел, чтобы текст не приписался предыдущему.
        return "other", len(line)
    return None


def segment(text: str) -> Segmented:
    sections, unknown = [], []
    kind, title, start, body_start = "header", "", 0, 0
    pos = 0
    for line in text.split("\n"):
        found = match_heading(line) if pos else None  # первая строка — шапка документа
        # Подзаголовок того же типа («ДИАГНОЗ» -> «Основной диагноз:») не делит раздел.
        if found and found[0] != kind and not (found[0] == "other" and DOC_TITLES.match(line.strip())):
            sections.append(Section(kind, title, start, body_start, pos))
            kind, length = found
            title, start = line[:length].strip(" \t:.#*—–"), pos
            body_start = pos + length + len(line[length:]) - len(line[length:].lstrip(" \t"))
            if kind == "other":
                unknown.append(title)
        pos += len(line) + 1
    sections.append(Section(kind, title, start, min(body_start, len(text)), len(text)))
    return Segmented(text, sections, unknown)
