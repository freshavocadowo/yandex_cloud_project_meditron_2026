"""Точка входа для запуска в браузере (Pyodide, GitHub Pages): без сервера, БД и LLM.

Возвращает те же словари, что API (`POST /api/extract`, `GET /api/schema`), сериализованные
в JSON, чтобы страницы работали одинаково с сервером и без него.
"""
from datetime import datetime, timezone
import json
import uuid

from .ingest import LoadError, load_bytes
from .pipeline import PIPELINE_VERSION, process
from .schema import DESCRIPTIONS, GROUPS


def schema() -> str:
    return json.dumps({"groups": GROUPS, "descriptions": DESCRIPTIONS, "pipeline_version": PIPELINE_VERSION,
                       "mode": "browser"}, ensure_ascii=False)


def extract(data: bytes, name: str) -> str:
    """JSON документа в формате Store.get(); при ошибке чтения — {"detail": код}, как HTTP 400 в API."""
    try:
        # из JS приходит Uint8Array (JsProxy в Pyodide), из Python — bytes
        raw = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
        source = load_bytes(raw, name or "document.md")
    except LoadError as exc:
        return json.dumps({"detail": str(exc)})
    extraction = process(source)
    return json.dumps({
        "id": str(uuid.uuid4()), "filename": source.name, "doc_id": source.doc_id, "sha256": extraction.sha256,
        "anon_text": extraction.anon_text, "warnings": extraction.warnings, "pipeline_version": PIPELINE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "json": extraction.result,
        "fields": extraction.evidence()["fields"],
    }, ensure_ascii=False)
