"""FastAPI: загрузка эпикриза -> JSON с подтверждающими фрагментами.

uvicorn app.api.main:app --host 0.0.0.0 --port 8000
"""
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..db import Store
from ..extract.llm import from_env
from ..ingest import LoadError, load_bytes
from ..ingest.loader import MAX_BYTES
from ..pipeline import PIPELINE_VERSION, process
from ..schema import DESCRIPTIONS, GROUPS

WEB = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(title="Эпикриз → JSON", version=PIPELINE_VERSION)
app.state.store = None
app.state.llm = from_env()


def store() -> Store:
    if app.state.store is None:
        app.state.store = Store.from_env()
    return app.state.store


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/inspect", include_in_schema=False)
def inspect() -> FileResponse:
    return FileResponse(WEB / "inspect.html")


@app.get("/api/schema")
def schema() -> dict:
    return {"groups": GROUPS, "descriptions": DESCRIPTIONS, "pipeline_version": PIPELINE_VERSION,
            "mode": "hybrid" if app.state.llm else "rules-only"}


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)) -> dict:
    data = await file.read(MAX_BYTES + 1)
    try:
        source = load_bytes(data, file.filename or "document.md")
    except LoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    extraction = process(source, app.state.llm)
    return store().get(store().save(source.name, extraction, PIPELINE_VERSION))


@app.get("/api/results/{doc_id}")
def result(doc_id: str) -> dict:
    found = store().get(doc_id)
    if found is None:
        raise HTTPException(status_code=404, detail="not_found")
    return found


@app.get("/api/results/{doc_id}/download")
def download(doc_id: str) -> JSONResponse:
    found = result(doc_id)
    filename = f"{found['doc_id']}.json"
    # filename* (RFC 5987): имя файла может быть кириллическим
    return JSONResponse(found["json"], headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@app.get("/api/documents")
def documents(limit: int = 100) -> list[dict]:
    return store().list(limit)


# web/ целиком (img/, api.js, inspect.html): монтируется последним, чтобы не перекрывать маршруты выше
app.mount("/", StaticFiles(directory=WEB), name="web")
