"""Проверка значений и цитат-подтверждений перед записью результата.

Значение остаётся в результате, только если оно проходит контракт schema.check_value
и его цитата находится в обезличенном тексте. Иначе — значение по умолчанию и
предупреждение: защита от галлюцинаций LLM и ошибок правил.
"""
from difflib import SequenceMatcher
import re

from .extract.rules import Finding
from .schema import FIELDS, check_value, default

FUZZY_MIN = 0.9


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def locate(text: str, quote: str) -> tuple[int, int] | None:
    """Позиция цитаты в тексте: точное совпадение, затем без учёта пробелов/регистра, затем fuzzy ≥ 0.9."""
    quote = quote.strip()
    if not quote:
        return None
    pos = text.find(quote)
    if pos != -1:
        return pos, pos + len(quote)
    squashed = _squash(quote)
    pattern = r"\s+".join(map(re.escape, squashed.split(" ")))
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return m.start(), m.end()
    # Fuzzy: окно длиной с цитату с шагом в четверть цитаты, затем уточнение границ по блокам совпадения.
    n = len(quote)
    if n < 8:
        return None
    best, best_pos = 0.0, None
    for start in range(0, max(1, len(text) - n + 1), max(1, n // 4)):
        window = text[start:start + n + n // 4]
        ratio = SequenceMatcher(None, quote.lower(), window.lower(), autojunk=False).ratio()
        if ratio > best:
            best, best_pos = ratio, start
    if best_pos is None:
        return None
    window = text[best_pos:best_pos + n + n // 4]
    matcher = SequenceMatcher(None, quote.lower(), window.lower(), autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size]
    if not blocks:
        return None
    start, end = best_pos + blocks[0].b, best_pos + blocks[-1].b + blocks[-1].size
    if SequenceMatcher(None, quote.lower(), text[start:end].lower(), autojunk=False).ratio() < FUZZY_MIN:
        return None
    return start, end


def verify(text: str, findings: dict[str, Finding]) -> tuple[dict[str, Finding], list[str]]:
    """Финальная проверка: формат значения + подтверждение цитатой."""
    checked, warnings = {}, []
    for key in FIELDS:
        f = findings.get(key) or Finding(default(key), source="default")
        if (code := check_value(key, f.value)) is not None:
            warnings.append(f"{code}:{key}")
            f = Finding(default(key), source="default")
        elif f.source != "default":
            if not (0 <= f.start < f.end <= len(text) and text[f.start:f.end] == f.evidence):
                span = locate(text, f.evidence)
                if span is None:
                    warnings.append(f"evidence_not_found:{key}")
                    f = Finding(default(key), source="default")
                else:
                    f = Finding(f.value, text[span[0]:span[1]], span[0], span[1], f.source)
        checked[key] = f
    return checked, warnings
