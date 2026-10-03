import codecs

import pytest

from app.ingest import LoadError, discover, load_bytes, load_path

TEXT = ("Выписной эпикриз\nДата госпитализации 24.04.2021; дата выписки 28.04.2021.\n\n"
        "ДИАГНОЗ ПРИ ВЫПИСКЕ\nОсновной диагноз: ИБС. Острый инфаркт миокарда нижней стенки. Код МКБ-10 I21.1.\n"
        "ИССЛЕДОВАНИЯ\nКреатинин 110 мкмоль/л; глюкоза 5,0 ммоль/л.\n")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp1251", "koi8_r"])
def test_encodings_give_same_text_and_digest(encoding):
    reference = load_bytes(TEXT.encode(), "train-0001.md")
    source = load_bytes(TEXT.encode(encoding), "train-0001.md")
    assert (source.text, source.sha256, source.doc_id) == (TEXT, reference.sha256, "train-0001")


def test_newlines_bom_and_unicode_normalized():
    decomposed = "Сахарный диабет отрицает.\r\nНе курит.\rЙ"
    source = load_bytes(codecs.BOM_UTF8 + decomposed.encode(), "a.txt")
    assert source.text == "Сахарный диабет отрицает.\nНе курит.\nЙ"
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
    assert load_path(tmp_path / "train-0001.TXT").doc_id == "train-0001"


def test_discover_errors(tmp_path):
    with pytest.raises(LoadError, match="input_dir_not_found"):
        discover(tmp_path / "missing")
    (tmp_path / "train-0001.md").write_text("x", encoding="utf-8")
    (tmp_path / "train-0001.txt").write_text("x", encoding="utf-8")
    with pytest.raises(LoadError, match="duplicate_document_stem"):
        discover(tmp_path)
