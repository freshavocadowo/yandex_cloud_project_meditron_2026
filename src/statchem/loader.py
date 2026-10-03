"""Read .md/.txt discharge summaries into one normalized text form.

All downstream offsets (sections, masks, evidence quotes) refer to the string
returned here, so normalization is fixed and minimal: BOM removed, line breaks
unified to "\\n", Unicode NFC. Nothing else is rewritten.
"""
from dataclasses import dataclass
import codecs
import hashlib
from pathlib import Path
import unicodedata

from charset_normalizer import from_bytes

EXTENSIONS = (".md", ".txt")
MAX_BYTES = 2_000_000  # a discharge summary is ~5 KB; larger input is not a document
BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))
# Legacy Cyrillic encodings seen in Russian clinical exports.
FALLBACKS = ["cp1251", "koi8_r", "cp866", "mac_cyrillic"]


class LoadError(ValueError):
    """str(exc) is a stable error code without paths or content, safe for logs."""


@dataclass(frozen=True)
class Source:
    name: str
    text: str
    encoding: str
    sha256: str  # of normalized text: same content in cp1251 and utf-8 gives one digest


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
    if Path(name).suffix.lower() not in EXTENSIONS:
        raise LoadError("unsupported_extension")
    if len(data) > MAX_BYTES:
        raise LoadError("document_too_large")
    text, encoding = decode(data)
    if "\x00" in text:
        raise LoadError("binary_content")
    text = normalize(text)
    if not text.strip():
        raise LoadError("empty_document")
    return Source(name, text, encoding, hashlib.sha256(text.encode()).hexdigest())


def load_path(path: Path) -> Source:
    if path.stat().st_size > MAX_BYTES:
        raise LoadError("document_too_large")
    return load_bytes(path.read_bytes(), path.name)


def discover(input_dir: Path) -> list[Path]:
    """Documents directly in input_dir, sorted; hidden and office lock files skipped."""
    if not input_dir.is_dir():
        raise LoadError("input_dir_not_found")
    paths = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS
                   and not p.name.startswith((".", "~$")))
    stems = [p.stem for p in paths]
    # train-0001.md and train-0001.txt would overwrite one result/train-0001.json.
    if len(stems) != len(set(stems)):
        raise LoadError("duplicate_document_stem")
    return paths
