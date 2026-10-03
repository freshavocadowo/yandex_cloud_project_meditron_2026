"""Основа конвейера: loader -> anonymizer -> segmenter.

python -m app.preprocess --input data/documents --output out/preprocessed
На каждый документ: <id>.anon.md (обезличенный текст) и <id>.sections.json;
summary.json — сводка для проверки словарей заголовков и обезличивания.
"""
from collections import Counter
from dataclasses import asdict, dataclass
import argparse
import json
from pathlib import Path
import sys
import time

from .anonymize import Anonymized, anonymize
from .ingest import LoadError, Source, discover, load_path
from .segment import Segmented, segment

# Без этих разделов извлечение признаков заведомо неполное.
REQUIRED_KINDS = ("diagnosis", "exam", "ecg", "labs", "therapy")


@dataclass
class Prepared:
    source: Source
    anon: Anonymized
    doc: Segmented  # сегментирован обезличенный текст: смещения цитат — в нём

    def warnings(self) -> list[str]:
        kinds = {s.kind for s in self.doc.sections}
        found = [f"residual_{k}" for k in self.anon.residual]
        found += [f"missing_section_{k}" for k in REQUIRED_KINDS if k not in kinds]
        return found + [f"unknown_heading:{h}" for h in self.doc.unknown_headings]

    def report(self) -> dict:
        return {"doc_id": self.source.doc_id, "encoding": self.source.encoding, "sha256": self.source.sha256,
                "masked": [asdict(s) for s in self.anon.spans],
                "sections": [asdict(s) for s in self.doc.sections], "warnings": self.warnings()}


def prepare(source: Source) -> Prepared:
    anon = anonymize(source.text)
    return Prepared(source, anon, segment(anon.text))


def write_json(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(input_dir: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    items, kinds, warnings = [], Counter(), Counter()
    for path in discover(input_dir):
        try:
            prepared = prepare(load_path(path))
        except LoadError as exc:
            items.append({"doc_id": path.stem, "status": "error", "error": str(exc)})
            continue
        report = prepared.report()
        (output_dir / f"{path.stem}.anon.md").write_text(prepared.anon.text, encoding="utf-8")
        write_json(output_dir / f"{path.stem}.sections.json", report)
        kinds.update({s.kind for s in prepared.doc.sections})
        warnings.update(w.split(":")[0] if w.startswith("unknown_heading") else w for w in report["warnings"])
        items.append({"doc_id": path.stem, "status": "review" if report["warnings"] else "ok",
                      "warnings": report["warnings"]})
    summary = {"documents": len(items), "errors": sum(i["status"] == "error" for i in items),
               "needs_review": sum(i["status"] == "review" for i in items),
               "seconds": round(time.perf_counter() - started, 3),
               "documents_with_section": dict(sorted(kinds.items())), "warnings": dict(warnings), "items": items}
    write_json(output_dir / "summary.json", summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("out/preprocessed"))
    args = parser.parse_args(argv)
    try:
        summary = run(args.input, args.output)
    except LoadError as exc:
        print(f"Запуск невозможен: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in summary.items() if k != "items"}, ensure_ascii=False, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
