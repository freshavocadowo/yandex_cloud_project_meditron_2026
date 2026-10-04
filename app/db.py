"""Хранилище обезличенных документов и результатов.

DATABASE_URL: postgresql://user:pass@host/db (нужен psycopg) или sqlite:///path.db
(по умолчанию sqlite:///out/meditron.db). Исходный текст не хранится — только
обезличенный, значения и цитаты.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid

from .pipeline import Extraction
from .schema import GROUP_OF

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL, anon_text TEXT NOT NULL,
    status TEXT NOT NULL, error TEXT, warnings TEXT, pipeline_version TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS extractions (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, group_name TEXT NOT NULL,
    field TEXT NOT NULL, value TEXT NOT NULL, evidence TEXT, ev_start INTEGER, ev_end INTEGER, source TEXT NOT NULL,
    PRIMARY KEY (document_id, field));
CREATE TABLE IF NOT EXISTS results (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE, json TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class Store:
    def __init__(self, url: str):
        self.url = url
        self.lock = threading.Lock()
        if url.startswith(("postgres://", "postgresql://")):
            import psycopg  # опциональная зависимость для Yandex Managed PostgreSQL

            self.conn = psycopg.connect(url, autocommit=True)
            self.mark = "%s"
            with self.conn.cursor() as cur:
                cur.execute(SCHEMA)  # без параметров psycopg выполняет несколько команд за раз
        else:
            path = url.removeprefix("sqlite:///") if url.startswith("sqlite:///") else url
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.executescript(SCHEMA)
            self.mark = "?"

    @classmethod
    def from_env(cls) -> "Store":
        return cls(os.environ.get("DATABASE_URL", "sqlite:///out/meditron.db"))

    def _execute(self, sql: str, params=(), many=False):
        sql = sql.replace("?", self.mark)
        with self.lock:
            cur = self.conn.cursor()
            (cur.executemany if many else cur.execute)(sql, params)
            rows = cur.fetchall() if cur.description else []
            if isinstance(self.conn, sqlite3.Connection):
                self.conn.commit()
            return rows

    def save(self, filename: str, extraction: Extraction, pipeline_version: str) -> str:
        doc_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (doc_id, filename, extraction.sha256, extraction.anon_text, "ok", None,
                       json.dumps(extraction.warnings, ensure_ascii=False), pipeline_version, now))
        self._execute("INSERT INTO extractions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      [(doc_id, GROUP_OF[key], key, f.value, f.evidence, f.start, f.end, f.source)
                       for key, f in extraction.findings.items()], many=True)
        self._execute("INSERT INTO results VALUES (?, ?, ?)",
                      (doc_id, json.dumps(extraction.result, ensure_ascii=False), now))
        return doc_id

    def get(self, doc_id: str) -> dict | None:
        rows = self._execute("SELECT d.id, d.filename, d.sha256, d.anon_text, d.warnings, d.pipeline_version, "
                             "d.created_at, r.json FROM documents d JOIN results r ON r.document_id = d.id "
                             "WHERE d.id = ?", (doc_id,))
        if not rows:
            return None
        id_, filename, sha256, anon_text, warnings, version, created_at, result = rows[0]
        fields = {field: {"value": value, "evidence": evidence, "start": start, "end": end, "source": source}
                  for field, value, evidence, start, end, source in self._execute(
                      "SELECT field, value, evidence, ev_start, ev_end, source FROM extractions "
                      "WHERE document_id = ?", (doc_id,))}
        return {"id": id_, "filename": filename, "doc_id": Path(filename).stem, "sha256": sha256,
                "anon_text": anon_text, "warnings": json.loads(warnings or "[]"), "pipeline_version": version,
                "created_at": created_at, "json": json.loads(result) if isinstance(result, str) else result,
                "fields": fields}

    def list(self, limit: int = 100) -> list[dict]:
        rows = self._execute("SELECT id, filename, status, pipeline_version, created_at FROM documents "
                             "ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(zip(("id", "filename", "status", "pipeline_version", "created_at"), row)) for row in rows]
