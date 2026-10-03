import pytest

from app.segment import match_heading, segment

CAPS = """ВЫПИСНОЙ ЭПИКРИЗ
Пациент: [ФИО]
Поступил 10.09.2021. Выписан 16.09.2021.

ДИАГНОЗ ПРИ ВЫПИСКЕ
Основной диагноз: ИБС. Код МКБ-10 I21.1.

ЭЛЕКТРОКАРДИОГРАФИЯ
ЭКГ от 24.04.2021: синусовый ритм, ЧСС 103 уд/мин.

ИССЛЕДОВАНИЯ
Креатинин 110 мкмоль/л.
Дополнительно: калий 4,7 ммоль/л.

СОЦИАЛЬНЫЙ СТАТУС
Работает.

РЕКОМЕНДАЦИИ
  1. АСК 100 мг утром
"""

INLINE = """Кардиологическое отделение
Пациент: [ФИО]
Основная жалоба — боль за грудиной.
Анамнез жизни: Не курит.
Клинический диагноз. Основной диагноз: Острый инфаркт миокарда передней стенки.
КАГ. Коронарография от 09.11.2020: ПМЖВ: стеноз 95%.
Повторный осмотр. 09.11.2020. АД 140/74 мм рт. ст.
Рекомендации. Постоянная терапия при выписке:
  1. АСК 100 мг вечером"""


def test_caps_layout():
    doc = segment(CAPS)
    assert [s.kind for s in doc.sections] == ["header", "diagnosis", "ecg", "labs", "other", "therapy"]
    assert doc.unknown_headings == ["СОЦИАЛЬНЫЙ СТАТУС"]
    assert "калий 4,7" in doc.bodies("labs")
    assert doc.bodies("ecg").strip() == "ЭКГ от 24.04.2021: синусовый ритм, ЧСС 103 уд/мин."
    assert doc.section_at(CAPS.index("I21.1")).kind == "diagnosis"


def test_inline_layout_bodies_start_after_heading():
    doc = segment(INLINE)
    assert [s.kind for s in doc.sections] == ["header", "history", "life_history", "diagnosis", "ca", "followup", "therapy"]
    assert doc.body(doc.of("ca")[0]).startswith("Коронарография от 09.11.2020")
    assert doc.body(doc.of("followup")[0]).startswith("09.11.2020. АД")
    assert doc.body(doc.of("history")[0]) == "боль за грудиной.\n"
    assert doc.body(doc.of("diagnosis")[0]).startswith("Основной диагноз:")


def test_sections_cover_text_without_gaps():
    for text in (CAPS, INLINE):
        doc = segment(text)
        assert doc.sections[0].start == 0 and doc.sections[-1].end == len(text)
        assert all(a.end == b.start for a, b in zip(doc.sections, doc.sections[1:]))


@pytest.mark.parametrize("line,kind", [
    ("ЭКГ при поступлении:", "ecg"), ("Эхо-КГ", "echo"), ("**Рентген ОГК:**", "xray"), ("## Лечение", "treatment"),
    ("Лабораторные данные. При поступлении глюкоза 5,8", "labs"), ("ДОПОЛНИТЕЛЬНО", "notes"),
    ("Дополнительно: калий 4,7", None), ("Лечение проводилось в условиях отделения.", None),
    ("ЭКГ от 13.01.2022: синусовый ритм", None), ("Коронарография от 10.10.2023: ПКА", None),
])
def test_match_heading(line, kind):
    found = match_heading(line)
    assert (found[0] if found else None) == kind


def test_corpus_has_key_sections(corpus):
    from app.anonymize import anonymize
    from app.ingest import load_path
    for path in corpus:
        doc = segment(anonymize(load_path(path).text).text)
        kinds = {s.kind for s in doc.sections}
        assert kinds >= {"diagnosis", "exam", "ecg", "labs", "therapy", "history"}, path.name
        assert doc.unknown_headings == [], path.name
