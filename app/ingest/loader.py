"""Чтение эпикризов .md/.txt в единый нормализованный текст.

Все последующие смещения (разделы, маски, цитаты-подтверждения) считаются от
строки, которую возвращает этот модуль, поэтому нормализация минимальна:
удаляется BOM, переводы строк приводятся к "\\n", Unicode — к NFC.
"""
from dataclasses import dataclass
import codecs
import hashlib
from pathlib import Path
import unicodedata

from charset_normalizer import from_bytes

EXTENSIONS = (".md", ".txt")
MAX_BYTES = 2_000_000  # эпикриз ~5 КБ; файл больше — не документ
BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))
# Кириллические кодировки старых медицинских выгрузок
FALLBACKS = ["cp1251", "koi8_r", "cp866", "mac_cyrillic"]


class LoadError(ValueError):
    """str(exc) — код ошибки без путей и содержимого, безопасен для логов."""


@dataclass(frozen=True)
class Source:
    doc_id: str  # базовое имя: train-0001.md -> result/train-0001.json
    name: str
    text: str
    encoding: str
    sha256: str  # от нормализованного текста: один текст в cp1251 и utf-8 даёт один хэш


def decode(data: bytes) -> tuple[str, str]:
    for bom, encoding in BOMS:
        if data.startswith(bom):
            return data.decode(encoding), encoding
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    match = from_bytes(data, cp_isolation=FALLBACKS).best()
    if match is None:
        raise LoadError("unknown_encoding")
    return str(match), match.encoding


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def load_bytes(data: bytes, name: str) -> Source:
    path = Path(name)
    if path.suffix.lower() not in EXTENSIONS:
        raise LoadError("unsupported_extension")
    if len(data) > MAX_BYTES:
        raise LoadError("document_too_large")
    text, encoding = decode(data)
    if "\x00" in text:
        raise LoadError("binary_content")
    text = normalize(text)
    if not text.strip():
        raise LoadError("empty_document")
    return Source(path.stem, path.name, text, encoding, hashlib.sha256(text.encode()).hexdigest())


def load_path(path: Path) -> Source:
    if path.stat().st_size > MAX_BYTES:
        raise LoadError("document_too_large")
    return load_bytes(path.read_bytes(), path.name)


def discover(input_dir: Path) -> list[Path]:
    """Документы непосредственно в input_dir, по имени; скрытые и lock-файлы Office пропускаются."""
    if not input_dir.is_dir():
        raise LoadError("input_dir_not_found")
    paths = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS
                   and not p.name.startswith((".", "~$")))
    stems = [p.stem for p in paths]
    # train-0001.md и train-0001.txt перезаписали бы один result/train-0001.json
    if len(stems) != len(set(stems)):
        raise LoadError("duplicate_document_stem")
    return paths
