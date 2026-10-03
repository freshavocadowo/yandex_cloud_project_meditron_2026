"""Independent corpus/output/evidence checks with no raw identifiers in output."""
from collections import Counter
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from statchem.contract import SCHEMA, TEMPLATE
from statchem.loader import discover, load_path
from statchem.pipeline import write_json
from statchem.privacy import residual_identifiers

source = Path("participant-kit-realistic-v2-100/documents")
structural_errors = 0
quote_errors = 0
residual_documents = 0
quoted_fields = 0
missing = Counter()
for path in discover(source):
    output = json.loads(Path("result", path.stem + ".json").read_text(encoding="utf-8"))
    report = json.loads(Path("reports/evidence", path.stem + ".json").read_text(encoding="utf-8"))
    masked = Path("reports/anonymized", path.stem + ".md").read_text(encoding="utf-8")
    try:
        Draft202012Validator(SCHEMA).validate(output)
    except Exception:
        structural_errors += 1
    residual_documents += bool(residual_identifiers(masked))
    assert len(masked) == len(load_path(path).text)
    for group in output.values():
        for field, value in group.items():
            missing[field] += value == "не указано"
    for e in report["evidence"].values():
        if e["quote"]:
            quoted_fields += 1
            quote_errors += masked[e["start"]:e["end"]] != e["quote"]
    for observation in report["laboratory_observations"]:
        quote_errors += masked[observation["start"]:observation["end"]] != observation["quote"]

summary = {"documents": len(discover(source)), "groups_per_document": len(TEMPLATE),
           "fields_per_document": sum(map(len, TEMPLATE.values())), "structural_errors": structural_errors,
           "quote_offset_errors": quote_errors, "residual_rule_identifier_documents": residual_documents,
           "quoted_fields": quoted_fields, "missing_by_field": dict(missing),
           "limitation": "Structural and coordinate audit; does not measure semantic accuracy or complete anonymization recall."}
write_json(Path("reports/audit.json"), summary)
print(json.dumps({k: v for k, v in summary.items() if k != "missing_by_field"}, ensure_ascii=False, indent=2))
if structural_errors or quote_errors or residual_documents:
    raise SystemExit(1)
