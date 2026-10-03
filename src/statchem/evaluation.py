"""Exact-match evaluation; reference annotations must be supplied separately."""
import json
from pathlib import Path

from .contract import FIELDS, Output


def evaluate(gold: Path, predictions: Path) -> dict:
    references = sorted(gold.glob("*.json"))
    if not references:
        raise ValueError("no_reference_annotations")
    counts = {f: {"matched": 0, "total": 0} for f in FIELDS}
    exact_docs = 0
    missing = 0
    for path in references:
        reference = json.loads(path.read_text(encoding="utf-8"))
        Output.model_validate(reference)
        target = predictions / path.name
        prediction = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        if not target.exists():
            missing += 1
        else:
            Output.model_validate(prediction)
        matches = 0
        for f, group in FIELDS.items():
            count = counts[f]
            count["total"] += 1
            if prediction.get(group, {}).get(f) == reference[group][f]:
                count["matched"] += 1
                matches += 1
        exact_docs += matches == len(FIELDS)
    groups = {}
    for f, g in FIELDS.items():
        stat = groups.setdefault(g, {"matched": 0, "total": 0})
        for k in stat:
            stat[k] += counts[f][k]
    matched = sum(c["matched"] for c in counts.values())
    total = sum(c["total"] for c in counts.values())
    return {"documents": len(references), "missing_predictions": missing, "exact_documents": exact_docs,
            "matched_fields": matched, "total_fields": total, "field_exact_match": matched / total,
            "by_field": counts, "by_group": groups,
            "limitation": "Metric applies only to supplied annotations. Reference quality must be independently reviewed."}
