"""Сборка статического сайта для GitHub Pages: web/ + Python-конвейер для Pyodide.

python scripts/build_pages.py [--out _site]
Проверить локально: python -m http.server -d _site 8080  →  http://localhost:8080
"""
import argparse
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# серверные части в браузере не нужны: FastAPI, БД, пакетный режим
SKIP = {"api", "db.py", "batch.py", "__pycache__"}


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out, ignore=shutil.ignore_patterns(".DS_Store"))
    (out / ".nojekyll").touch()  # отдавать файлы как есть, без Jekyll
    (out / "py").mkdir()
    with zipfile.ZipFile(out / "py" / "app.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted((ROOT / "app").rglob("*.py")):
            rel = path.relative_to(ROOT)
            if not SKIP.intersection(rel.parts):
                z.write(path, rel.as_posix())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "_site")
    build(parser.parse_args().out)
