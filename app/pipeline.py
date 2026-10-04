"""Один документ: loader -> anonymizer -> segmenter -> rules (+LLM) -> validator -> JSON.

Значения и цитаты относятся к обезличенному тексту; исходный текст дальше
prepare() не передаётся.
"""
from dataclasses import asdict, dataclass, field

from .extract import Finding, extract
from .extract.llm import LLMClient, fill_missing
from .ingest import Source
from .preprocess import Prepared, prepare
from .schema import FIELDS, nest
from .validate import verify

PIPELINE_VERSION = "0.2.0"


@dataclass
class Extraction:
    doc_id: str
    sha256: str
    anon_text: str
    findings: dict[str, Finding]
    warnings: list[str] = field(default_factory=list)

    @property
    def result(self) -> dict[str, dict[str, str]]:
        return nest({key: f.value for key, f in self.findings.items()})

    def evidence(self) -> dict:
        return {"doc_id": self.doc_id, "sha256": self.sha256, "pipeline_version": PIPELINE_VERSION,
                "fields": {key: asdict(self.findings[key]) for key in FIELDS}, "warnings": self.warnings}

    def filled(self) -> int:
        """Сколько значений подтверждено цитатой (не значение по умолчанию)."""
        return sum(f.source != "default" for f in self.findings.values())


def run(prepared: Prepared, llm: LLMClient | None = None) -> Extraction:
    text = prepared.anon.text
    findings = extract(prepared.doc)
    warnings = prepared.warnings()
    if llm is not None:
        findings, llm_warnings = fill_missing(llm, text, findings)
        warnings += llm_warnings
    findings, check_warnings = verify(text, findings)
    return Extraction(prepared.source.doc_id, prepared.source.sha256, text, findings, warnings + check_warnings)


def process(source: Source, llm: LLMClient | None = None) -> Extraction:
    return run(prepare(source), llm)
