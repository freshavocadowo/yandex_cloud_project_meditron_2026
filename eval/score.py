"""Оценка результатов: валидность, полнота, точность по полям и группам, подтверждаемость.

python -m eval.score --pred result --docs data/documents [--gold eval/gold] [--evidence result_evidence]

Точность считается только по документам, для которых есть эталон в --gold.
Сравнение после нормализации: регистр, ё/е, пробелы; числа — как числа (7.0 == 7).
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

from app.schema import FIELDS, GROUP_OF, GROUPS, default, flatten, validate


def norm(value) -> str:
    text = " ".join(str(value).split()).casefold().replace("ё", "е").rstrip(".")
    try:
        return repr(float(text.replace(",", ".")))
    except ValueError:
        return text


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def score(pred_dir: Path, doc_ids: list[str], gold_dir: Path | None = None, evidence_dir: Path | None = None) -> dict:
    present = valid = filled = 0
    invalid: dict[str, list[str]] = {}
    with_evidence = non_default = 0
    hits, totals = Counter(), Counter()
    mismatches = []
    for doc_id in doc_ids:
        pred = load(pred_dir / f"{doc_id}.json")
        if pred is None:
            invalid[doc_id] = ["missing_or_not_json"]
            continue
        present += 1
        errors = validate(pred)
        if errors:
            invalid[doc_id] = errors
            continue
        valid += 1
        values = flatten(pred)
        filled += sum(values[k] != default(k) for k in FIELDS)
        if evidence_dir is not None and (ev := load(evidence_dir / f"{doc_id}.json")):
            for key in FIELDS:
                if values[key] != default(key):
                    non_default += 1
                    with_evidence += bool(ev["fields"].get(key, {}).get("evidence"))
        gold = load(gold_dir / f"{doc_id}.json") if gold_dir else None
        if gold is None:
            continue
        expected = flatten(gold)
        for key in FIELDS:
            ok = norm(values[key]) == norm(expected.get(key, default(key)))
            hits[key] += ok
            totals[key] += 1
            if not ok:
                mismatches.append({"doc_id": doc_id, "field": key, "pred": values[key], "gold": expected.get(key)})
    n = len(doc_ids)
    summary = {
        "documents": n,
        "files_present": present,
        "valid_json": round(valid / n, 4) if n else None,
        "fill_rate": round(filled / (valid * len(FIELDS)), 4) if valid else None,
        "evidence_rate": round(with_evidence / non_default, 4) if non_default else None,
        "invalid": invalid,
    }
    if totals:
        group_hits, group_totals = defaultdict(int), defaultdict(int)
        for key in totals:
            group_hits[GROUP_OF[key]] += hits[key]
            group_totals[GROUP_OF[key]] += totals[key]
        summary.update({
            "gold_documents": totals[FIELDS[0]],
            "accuracy": round(sum(hits.values()) / sum(totals.values()), 4),
            "accuracy_by_group": {g: round(group_hits[g] / group_totals[g], 4) for g in GROUPS},
            "accuracy_by_field": {k: round(hits[k] / totals[k], 4) for k in FIELDS},
            "mismatches": mismatches,
        })
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pred", type=Path, default=Path("result"))
    parser.add_argument("--docs", type=Path, help="каталог входных документов: ожидаемый список файлов")
    parser.add_argument("--gold", type=Path, default=Path("eval/gold"))
    parser.add_argument("--evidence", type=Path, default=Path("result_evidence"))
    args = parser.parse_args(argv)
    source = args.docs if args.docs else args.pred
    doc_ids = sorted(p.stem for p in source.iterdir() if p.suffix in (".md", ".txt", ".json"))
    summary = score(args.pred, doc_ids, args.gold if args.gold.is_dir() else None,
                    args.evidence if args.evidence.is_dir() else None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["valid_json"] == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
