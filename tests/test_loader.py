import codecs
import json

import pytest

from statchem.loader import LoadError, discover, load_bytes, load_path
from statchem.pipeline import batch
from statchem.settings import Settings

TEXT = ("Выписной эпикриз\nДата госпитализации 24.04.2021; дата выписки 28.04.2021.\n\n"
        "ДИАГНОЗ ПРИ ВЫПИСКЕ\nОсновной диагноз: ИБС. Острый инфаркт миокарда нижней стенки левого желудочка "
        "с подъёмом ST. Код МКБ-10 I21.1.\nСопутствующие заболевания: Гипертоническая болезнь II стадии.\n\n"
        "ЭЛЕКТРОКАРДИОГРАФИЯ\nЭКГ от 24.04.2021: синусовый ритм, ЧСС 103 уд/мин.\n\n"
        "ИССЛЕДОВАНИЯ\nПервичные анализы от 24.04.2021: креатинин 110 мкмоль/л; глюкоза 5,0 ммоль/л.\n")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp1251", "koi8_r"])
def test_encodings_give_same_text_and_digest(encoding):
    reference = load_bytes(TEXT.encode(), "a.md")
    source = load_bytes(TEXT.encode(encoding), "a.md")
    assert source.text == TEXT
    assert source.sha256 == reference.sha256


def test_newlines_bom_and_unicode_normalized():
    decomposed = "Сахарный диабет отрицает. Рентген: застоя нет.\r\nКурение: не курит.\rЙ"
    source = load_bytes(codecs.BOM_UTF8 + decomposed.encode(), "a.txt")
    assert source.text == "Сахарный диабет отрицает. Рентген: застоя нет.\nКурение: не курит.\nЙ"
    assert source.encoding == "utf-8-sig"


@pytest.mark.parametrize("data,name,code", [
    (b"", "a.md", "empty_document"),
    (b" \r\n\t", "a.md", "empty_document"),
    (b"text", "a.docx", "unsupported_extension"),
    (b"a\x00b", "a.md", "binary_content"),
    (b"x" * 2_000_001, "a.md", "document_too_large"),
])
def test_rejected_inputs(data, name, code):
    with pytest.raises(LoadError, match=code):
        load_bytes(data, name)


def test_discover_filters_and_sorts(tmp_path):
    for name in ["train-0002.md", "train-0001.TXT", ".hidden.md", "~$lock.md", "notes.json"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "sub.md").mkdir()
    assert [p.name for p in discover(tmp_path)] == ["train-0001.TXT", "train-0002.md"]
    assert load_path(tmp_path / "train-0001.TXT").text == "x"


def test_discover_errors(tmp_path):
    with pytest.raises(LoadError, match="input_dir_not_found"):
        discover(tmp_path / "missing")
    (tmp_path / "train-0001.md").write_text("x", encoding="utf-8")
    (tmp_path / "train-0001.txt").write_text("x", encoding="utf-8")
    with pytest.raises(LoadError, match="duplicate_document_stem"):
        discover(tmp_path)


def test_batch_reads_txt_in_cp1251_and_isolates_bad_file(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "train-0001.txt").write_bytes(TEXT.replace("\n", "\r\n").encode("cp1251"))
    (docs / "train-0002.md").write_bytes(b"")
    settings = Settings()
    settings.use_ner = False
    summary = batch(docs, tmp_path / "result", tmp_path / "reports", settings)
    assert (summary["successful"], summary["failed"]) == (1, 1)
    assert [i["error_code"] for i in summary["items"] if i["status"] == "error"] == ["empty_document"]
    output = json.loads((tmp_path / "result" / "train-0001.json").read_text(encoding="utf-8"))
    assert output["даты эпизода"] == {"admission_date": "24.04.2021", "discharge_date": "28.04.2021"}
    assert output["диагноз"]["diagnosis_icd"] == "I21.1"
    assert output["Лабораторные данные"]["glu"] == "5.0"
