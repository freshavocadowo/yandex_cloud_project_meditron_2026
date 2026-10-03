"""Parse sections without changing characters: offsets always refer to the input."""
from dataclasses import dataclass
import hashlib
import re

from markdown_it import MarkdownIt

HEADINGS = {
    "diagnosis": r"(?:заключительный|клинический)?\s*диагноз(?: при выписке)?",
    "exam": r"первичный статус|данные осмотра|осмотр при поступлении|объективно при поступлении",
    "ecg": r"экг(?: при поступлении)?|электрокардиография|инструментальные данные",
    "echo": r"эхо[- ]?кг|эхокардиография|узи сердца",
    "xray": r"рентгенография грудной клетки|рентген огк|рентгенологические данные|р-графия органов грудной клетки",
    "ca": r"каг|коронарография|исследование коронарного русла|инвазивная диагностика",
    "labs": r"анализы крови|лабораторные (?:данные|исследования)|исследования",
    "therapy": r"рекомендации(?: при выписке)?|назначения при выписке|дальнейшее наблюдение",
    "treatment": r"провед[её]нное лечение|терапия в стационаре|лечение(?: и исход)?",
    "history": r"жалобы(?: и анамнез заболевания| при поступлении)?|анамнез заболевания|анамез заболевания|из анамнеза",
    "followup": r"состояние в динамике|данные наблюдения|контроль в динамике|повторный осмотр|контрольные исследования|течение (?:госпитализации|заболевания)|динамика в стационаре|памятка при выписке|план наблюдения|порядок амбулаторного контроля|консультации|консультативные заключения|заключения специалистов|осмотры специалистов|дополнительно",
}


@dataclass(frozen=True)
class Section:
    kind: str
    title: str
    start: int
    end: int


@dataclass
class Document:
    text: str
    sections: list[Section]
    digest: str
    markdown_tables: int

    def section_at(self, pos: int) -> Section:
        return next(s for s in self.sections if s.start <= pos < s.end)


def parse(text: str) -> Document:
    if not text.strip():
        raise ValueError("empty_document")
    boundaries = [(0, "header", "Начало документа")]
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip().lstrip("# ").strip("* ")
        for kind, pattern in HEADINGS.items():
            match = re.match(rf"^(?:{pattern})(?=$|[:.])", stripped, re.I)
            if match:
                if boundaries[-1][0] == offset:
                    boundaries[-1] = (offset, kind, match.group())
                else:
                    boundaries.append((offset, kind, match.group()))
                break
        offset += len(line)
    sections = [Section(kind, title, start, boundaries[i+1][0] if i+1 < len(boundaries) else len(text)) for i, (start, kind, title) in enumerate(boundaries)]
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    return Document(text, sections, hashlib.sha256(text.encode()).hexdigest(), sum(t.type == "table_open" for t in tokens))
