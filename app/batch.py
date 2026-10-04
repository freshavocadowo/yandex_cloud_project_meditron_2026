"""Пакетная обработка: каталог .md/.txt -> result/<имя>.json (+ result_evidence/<имя>.json).

python -m app.batch --input data/documents --output result --workers 8

Файл результата создаётся для 100% входов: при ошибке чтения или извлечения
пишется шаблон со значениями по умолчанию, причина — в logs/failed.csv.
Повторный запуск пропускает документы, у которых совпадают sha256 текста и
версия конвейера (кэш — файлы result_evidence). LLM включается переменными
LLM_BASE_URL/LLM_MODEL (см. app/extract/llm.py), иначе — rules-only.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import csv
import json
from pathlib import Path
import sys
import time

from .extract.llm import LLMClient, from_env
from .ingest import LoadError, discover, load_path
from .pipeline import PIPELINE_VERSION, Extraction, process
from .preprocess import write_json
from .schema import FIELDS, empty, validate


def cached(evidence_path: Path, result_path: Path, sha256: str) -> bool:
    if not (evidence_path.is_file() and result_path.is_file()):
        return False
    try:
        meta = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return meta.get("sha256") == sha256 and meta.get("pipeline_version") == PIPELINE_VERSION


def handle(path: Path, output: Path, evidence_dir: Path, llm: LLMClient | None, force: bool, store=None) -> dict:
    result_path, evidence_path = output / f"{path.stem}.json", evidence_dir / f"{path.stem}.json"
    try:
        source = load_path(path)
    except LoadError as exc:
        write_json(result_path, empty())
        return {"doc_id": path.stem, "status": "failed", "error": str(exc)}
    if not force and cached(evidence_path, result_path, source.sha256):
        return {"doc_id": path.stem, "status": "cached"}
    try:
        extraction = process(source, llm)
    except Exception as exc:  # сбой одного документа не останавливает пакет
        write_json(result_path, empty())
        return {"doc_id": path.stem, "status": "failed", "error": f"extract:{type(exc).__name__}"}
    result = extraction.result
    errors = validate(result)
    if errors:  # не должно случаться: verify() уже привёл значения к контракту
        write_json(result_path, empty())
        return {"doc_id": path.stem, "status": "failed", "error": "invalid:" + ",".join(errors[:3])}
    write_json(result_path, result)
    write_json(evidence_path, extraction.evidence())
    if store is not None:
        store.save(source.name, extraction, PIPELINE_VERSION)
    return {"doc_id": path.stem, "status": "ok", "filled": extraction.filled(), "warnings": extraction.warnings}


def run(input_dir: Path, output: Path, evidence_dir: Path, workers: int = 8, llm: LLMClient | None = None,
        force: bool = False, log_dir: Path = Path("logs"), store=None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    paths = discover(input_dir)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        items = list(pool.map(lambda p: handle(p, output, evidence_dir, llm, force, store), paths))
    failed = [i for i in items if i["status"] == "failed"]
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "failed.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["doc_id", "error"])
        writer.writerows([i["doc_id"], i["error"]] for i in failed)
    done = [i for i in items if i["status"] == "ok"]
    return {"documents": len(items), "ok": len(done), "cached": sum(i["status"] == "cached" for i in items),
            "failed": len(failed), "seconds": round(time.perf_counter() - started, 3),
            "mode": "hybrid" if llm else "rules-only", "pipeline_version": PIPELINE_VERSION,
            "evidence_rate": round(sum(i["filled"] for i in done) / (len(done) * len(FIELDS)), 3) if done else None,
            "with_warnings": sum(bool(i["warnings"]) for i in done)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("result"))
    parser.add_argument("--evidence", type=Path, default=Path("result_evidence"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true", help="пересчитать даже закэшированные документы")
    parser.add_argument("--no-llm", action="store_true", help="не обращаться к LLM, даже если она настроена")
    parser.add_argument("--db", action="store_true", help="сохранить результаты в БД (DATABASE_URL)")
    args = parser.parse_args(argv)
    store = None
    if args.db:
        from .db import Store
        store = Store.from_env()
    try:
        summary = run(args.input, args.output, args.evidence, args.workers, None if args.no_llm else from_env(),
                      args.force, store=store)
    except LoadError as exc:
        print(f"Запуск невозможен: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
