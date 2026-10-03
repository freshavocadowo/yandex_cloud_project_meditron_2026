"""Local masking; never store identifier values. Equal-length masks retain offsets."""
from dataclasses import dataclass
from functools import lru_cache
import re

DATE = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"
PATTERNS = {
    "name": r"(?:Пациент(?:ка)?|Ф\.?\s*И\.?\s*О\.?|Лечащий врач|Врач)\s*:\s*([^\n,;.(]+)",
    "birth": rf"(?:д\.?\s*р\.?|дата рождения|родил[а-яё]+)\s*[: ]*({DATE})",
    "age": r"(?:возраст\s*[: ]*)?(\b\d{1,3}\s*(?:лет|год(?:а)?))\b",
    "record": r"(?:история болезни\s*№|№\s*истории болезни|номер истории(?: болезни)?|медицинская карта\s*№)\s*[: ]*(\d+)",
    "email": r"\b([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})\b",
    "phone": r"(?<!\d)((?:\+7|8)[ ()-]*\d{3}[ ()-]*\d{3}[ -]*\d{2}[ -]*\d{2})(?!\d)",
    "snils": r"\b(\d{3}-\d{3}-\d{3}[ -]\d{2})\b",
    "identifier": r"(?:паспорт|СНИЛС|полис(?: ОМС)?|ОМС)\s*[:№ ]+([^\n,;]+)",
    "address": r"(?:адрес(?: проживания| регистрации)?|место жительства)\s*:\s*([^\n]+)",
}


@dataclass
class Masked:
    text: str
    spans: list[dict]
    residual: list[str]
    ner_used: bool


@lru_cache(maxsize=1)
def ner_components():
    from natasha import Segmenter, NewsEmbedding, NewsNERTagger
    return Segmenter(), NewsNERTagger(NewsEmbedding())


def ner_spans(text: str):
    from natasha import Doc
    segmenter, tagger = ner_components()
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_ner(tagger)
    # News NER misclassifies capitalized clinical headings as people/places.
    # Exclude only a closed vocabulary of common clinical words, never names.
    clinical_words = {"коронарография", "эхокардиография", "электрокардиография", "рентгенография",
                      "элевация", "st", "одышки", "лечение", "состояние", "консультация", "кардиолога",
                      "кардиологическое", "отделение", "выписной", "пациентка"}
    spans = []
    for s in doc.spans:
        raw = text[s.start:s.stop]
        tokens = re.findall(r"[а-яёa-z]+", raw.lower())
        label = bool(re.fullmatch(r"Ф\.?\s*И\.?\s*О\.?\s*:?", raw, re.I))
        if s.type in {"PER", "LOC"} and not label and not (tokens and all(w in clinical_words for w in tokens)):
            spans.append((s.start, s.stop, s.type))
    return spans


def residual_identifiers(text: str) -> list[str]:
    found = []
    for kind, pattern in PATTERNS.items():
        for m in re.finditer(pattern, text, re.I):
            # An empty doctor signature and already masked context are safe.
            if re.search(r"[\w\d]", m.group(1).replace("█", "")):
                found.append(kind)
    if re.search(r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна)\s+[А-ЯЁ][а-яё]+\b", text):
        found.append("unlabelled_name")
    return sorted(set(found))


def anonymize(text: str, use_ner: bool = True) -> Masked:
    spans = []
    for kind, pattern in PATTERNS.items():
        spans.extend((m.start(1), m.end(1), kind) for m in re.finditer(pattern, text, re.I))
    if use_ner:
        spans.extend(ner_spans(text))
    # Merge overlaps; no identifier value is added to the map.
    merged = []
    for start, end, kind in sorted(spans):
        if merged and start <= merged[-1]["end"]:
            merged[-1]["end"] = max(end, merged[-1]["end"])
        else:
            merged.append({"start": start, "end": end, "kind": kind})
    chars = list(text)
    for span in merged:
        for i in range(span["start"], span["end"]):
            if chars[i] not in "\r\n":
                chars[i] = "█"
    masked = "".join(chars)
    remaining = residual_identifiers(masked)
    if use_ner and ner_spans(masked):
        remaining.append("ner_residual")
    return Masked(masked, merged, remaining, use_ner)
