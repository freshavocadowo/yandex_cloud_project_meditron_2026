"""Orchestration, conservative fact verification and isolated batch failures."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

from .contract import FIELDS, MISSING, assemble, validate_value
from .parser import parse
from .privacy import anonymize, residual_identifiers
from .rules import Fact, defaults, extract, negated
from .settings import Settings


@dataclass
class Processed:
    output: dict
    report: dict
    masked_text: str


def dictionary() -> dict:
    from importlib.resources import files
    return json.loads(files("statchem").joinpath("data/fields.json").read_text(encoding="utf-8"))


def verify_candidate(candidate, doc, facts: dict[str, Fact]) -> tuple[Fact | None, str | None]:
    f, value, quote = candidate.field, candidate.value, candidate.quote
    if not validate_value(f, value) or not quote or "█" in quote or residual_identifiers(value):
        return None, f"invalid_candidate:{f}"
    positions = [m.start() for m in re.finditer(re.escape(quote), doc.text)]
    if len(positions) != 1:
        return None, f"quote_not_unique_or_missing:{f}"
    a, b = positions[0], positions[0] + len(quote)
    sec = doc.section_at(a)
    if b > sec.end:
        return None, f"quote_crosses_sections:{f}"
    if candidate.context in {"repeat", "history", "cancellation"}:
        return None, f"ineligible_context:{f}"
    expected = {
        "даты эпизода": {"header"}, "диагноз": {"diagnosis"}, "осмотр при поступлении": {"exam"},
        "ЭКГ": {"ecg"}, "ЭХО-КГ": {"echo"}, "рентген грудной полости": {"xray"},
        "коронарография": {"ca"}, "Лабораторные данные": {"labs"}, "медикаментозная терапия": {"therapy"},
    }[FIELDS[f]]
    if f == "smoking":
        expected = {"history", "exam"}
    if f == "tlt":
        expected = {"diagnosis", "treatment"}
    if sec.kind not in expected:
        return None, f"wrong_section:{f}"
    line_start = max(sec.start, doc.text.rfind("\n", sec.start, a) + 1)
    prefix = doc.text[line_start:a]
    if FIELDS[f] == "Лабораторные данные" and re.search(r"контрол|повтор|перед выпиской|ранее|анамнез", prefix, re.I):
        return None, f"ineligible_measurement:{f}"
    positive_fields = {"art_hyper", "atr_fibril", "copd", "dm", "ecg_avb", "ecg_elevation", "tlt"}
    if ((f in positive_fields and value == "1") or FIELDS[f] == "медикаментозная терапия") and negated(doc.text, a, b):
        return None, f"negation_in_source_context:{f}"
    # Reapply the same deterministic coding to the exact quote. Merely appearing in
    # the document is not sufficient: 'creatinine 99' cannot justify value 103.
    wrapper = {"header": "", "diagnosis": "Диагноз:\n", "exam": "Первичный статус:\n", "ecg": "ЭКГ:\n", "echo": "ЭхоКГ:\n", "xray": "Рентген ОГК:\n", "ca": "КАГ:\n", "labs": "Анализы крови:\n", "therapy": "Рекомендации:\n", "history": "Из анамнеза:\n", "treatment": "Лечение:\n"}[sec.kind]
    quote_facts, _ = extract(parse(wrapper + quote))
    supported = quote_facts.get(f)
    if supported and supported.value == value:
        return Fact(f, value, quote, a, b, sec.kind, candidate.context, "yandex"), None
    # For open text fields, accept only verbatim positive fragments of the right
    # source, with the feature name present. Numeric/category values never use this path.
    anchors = {"ckd": r"ХБП|болезнь почек", "hf": r"ХСН|сердечная недостаточность", "echo_mr": r"митральн.*регургитац", "echo_zone": r"гипокинез|акинез", "rg_pc": r"засто|от[её]к"}
    if f in anchors and value in quote and re.search(anchors[f], value, re.I) and not negated(doc.text, a, b):
        return Fact(f, value, quote, a, b, sec.kind, candidate.context, "yandex"), None
    return None, f"value_not_supported_by_quote:{f}"


def process(text: str, settings: Settings | None = None, mode="rules", extractor=None) -> Processed:
    if mode not in {"rules", "yandex"}:
        raise ValueError("invalid_mode")
    settings = settings or Settings()
    if mode == "yandex":
        settings.require_cloud()
    original = parse(text)
    masked = anonymize(text, settings.use_ner)
    if masked.residual:
        raise ValueError("residual_identifiers")
    doc = parse(masked.text)
    facts, warnings = extract(doc)
    if mode == "yandex":
        if extractor is None:
            from .yandex import YandexExtractor
            extractor = YandexExtractor(settings)
        response = extractor.extract(masked.text, dictionary())
        for candidate in response.candidates:
            accepted, error = verify_candidate(candidate, doc, facts)
            if error:
                warnings.append(error)
                continue
            previous = facts.get(candidate.field)
            if previous and previous.value != accepted.value:
                warnings.append(f"rule_model_conflict:{candidate.field}")
                # Keep the deterministic primary measurement, require human review.
                continue
            if not previous:
                facts[candidate.field] = accepted
    values = defaults()
    values.update({f: fact.value for f, fact in facts.items()})
    if values["ca_fact"] != "Y":
        for f in ("ca_date", "ca_lad", "rca"):
            values[f] = MISSING
            facts.pop(f, None)
    if values["admission_date"] != MISSING and values["discharge_date"] != MISSING:
        if datetime.strptime(values["discharge_date"], "%d.%m.%Y") < datetime.strptime(values["admission_date"], "%d.%m.%Y"):
            warnings.append("discharge_before_admission")
    output = assemble(values)
    evidence = {}
    for f in FIELDS:
        if f in facts:
            fact = facts[f]
            if doc.text[fact.start:fact.end] != fact.quote or not fact.quote:
                raise ValueError("invalid_evidence_offset")
            evidence[f] = {**fact.export(), "verified": True, "basis": "quoted_fact"}
        else:
            evidence[f] = {"field": f, "value": values[f], "basis": "coding_default" if values[f] != MISSING else "not_found", "quote": None, "verified": False}
    if not settings.use_ner:
        warnings.append("rules_only_anonymization")
    report = {"mode": mode, "status": "review" if warnings else "ok", "source_sha256": original.digest,
              "privacy": {"ner_used": masked.ner_used, "masked_spans": masked.spans, "residual_count": 0,
                          "coordinate_system": "Unicode character offsets, zero-based, end-exclusive; unchanged after masking"},
              "sections": [{"kind": s.kind, "start": s.start, "end": s.end} for s in doc.sections],
              "markdown_tables": doc.markdown_tables, "warnings": sorted(set(warnings)), "evidence": evidence}
    # Preserve repeated laboratory observations for review, separately from selected facts.
    from .rules import NUM, SEP
    observations = []
    for f, label in {"crea": "креатинин", "glu": "глюкоза", "hb": "гемоглобин", "ldl": "ХС[-–]ЛПНП|холестерин ЛПНП", "leucocytes": "лейкоциты", "thrombocytes": "тромбоциты", "tot_chol": "общий холестерин"}.items():
        for m in re.finditer(rf"(?:{label}){SEP}{NUM}", doc.text, re.I):
            sec = doc.section_at(m.start())
            if sec.kind not in {"labs", "followup"}:
                continue
            selected = f in facts and facts[f].start == m.start()
            observations.append({"field": f, "value": m.group(1).replace(",", "."), "quote": m.group(),
                                 "start": m.start(), "end": m.end(), "section": sec.kind,
                                 "context": "primary" if selected else "unselected_or_repeat", "selected": selected})
    report["laboratory_observations"] = sorted(observations, key=lambda o: o["start"])
    return Processed(output, report, masked.text)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def export_id(path: Path) -> str:
    # Official corpus names are safe; arbitrary filenames could contain identifiers.
    if re.fullmatch(r"(?:train|test|doc|synthetic)-\d+", path.stem):
        return path.stem
    return "doc-" + hashlib.sha256(path.name.encode()).hexdigest()[:16]


def batch(input_dir: Path, output_dir: Path, reports_dir: Path, settings: Settings, mode="rules", limit: int | None = None):
    if mode == "yandex":
        settings.require_cloud()
        from .yandex import YandexExtractor
        extractor = YandexExtractor(settings)
    else:
        extractor = None
    paths = sorted(input_dir.glob("*.md"))
    if not paths:
        raise ValueError("no_markdown_documents")
    if limit is not None:
        paths = paths[:limit]
    # Preflight prevents writing over the inputs or colliding with report files.
    if output_dir.resolve() == input_dir.resolve() or output_dir.resolve() == (reports_dir / "evidence").resolve():
        raise ValueError("overlapping_output_directories")
    seen = {}
    items = []
    run_start = time.perf_counter()
    for path in paths:
        stem = export_id(path)
        start = time.perf_counter()
        target = output_dir / (stem + ".json")
        evidence_target = reports_dir / "evidence" / (stem + ".json")
        try:
            text = path.read_bytes().decode("utf-8-sig")
            digest = hashlib.sha256(text.encode()).hexdigest()
            result = process(text, settings, mode, extractor)
            if digest in seen:
                result.report["warnings"].append("duplicate_document")
                result.report["status"] = "review"
            seen[digest] = stem
            write_json(target, result.output)
            write_json(evidence_target, result.report)
            masked_path = reports_dir / "anonymized" / (stem + ".md")
            masked_path.parent.mkdir(parents=True, exist_ok=True)
            masked_path.write_text(result.masked_text, encoding="utf-8")
            items.append({"document": stem, "status": result.report["status"], "warnings": result.report["warnings"], "quoted_fields": sum(e["verified"] for e in result.report["evidence"].values()), "seconds": round(time.perf_counter()-start, 4)})
        except Exception as exc:
            # An old successful export must not masquerade as the new failed run.
            for old in (target, evidence_target, reports_dir / "anonymized" / (stem + ".md")):
                old.unlink(missing_ok=True)
            known = {"empty_document", "residual_identifiers", "invalid_field_value", "invalid_evidence_offset", "incomplete_model_response", "empty_model_response"}
            code = str(exc) if str(exc) in known else "processing_failed"
            items.append({"document": stem, "status": "error", "error_type": type(exc).__name__, "error_code": code, "seconds": round(time.perf_counter()-start, 4)})
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "mode": mode, "model": settings.model if mode == "yandex" else None,
               "documents": len(items), "successful": sum(i["status"] in {"ok", "review"} for i in items),
               "needs_review": sum(i["status"] == "review" for i in items), "failed": sum(i["status"] == "error" for i in items),
               "seconds": round(time.perf_counter()-run_start, 4), "items": items,
               "quality": "Structure and quote checks only; no human-verified accuracy measurement."}
    write_json(reports_dir / "run.json", summary)
    return summary
