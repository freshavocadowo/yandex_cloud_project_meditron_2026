import os
from pathlib import Path

import pytest

# Корпус не хранится в репозитории: путь через CORPUS_DIR или data/documents.
CORPUS = Path(os.environ.get("CORPUS_DIR", "data/documents"))


@pytest.fixture
def corpus() -> list[Path]:
    paths = sorted(CORPUS.glob("*.md")) if CORPUS.is_dir() else []
    if not paths:
        pytest.skip("корпус не найден: задайте CORPUS_DIR")
    return paths
