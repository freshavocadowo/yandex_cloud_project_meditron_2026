from fastapi.testclient import TestClient

from app.api.main import app
from app.db import Store

DOC = ("ВЫПИСНОЙ ЭПИКРИЗ\nПациент: Иван Петрович Сидоров, д.р. 01.02.1950, возраст 72 года.\n"
       "Поступил 01.03.2022. Выписан 08.03.2022.\n\nДиагноз:\nОИМ нижней стенки с подъёмом ST. Код МКБ-10 I21.1.\n")


def client() -> TestClient:
    app.state.store = Store("sqlite:///:memory:")
    app.state.llm = None
    return TestClient(app)


def test_upload_result_download_list():
    c = client()
    response = c.post("/api/extract", files={"file": ("пациент-1.md", DOC.encode("cp1251"), "text/markdown")})
    assert response.status_code == 200
    body = response.json()
    assert body["json"]["диагноз"]["type_acs"] == "STEMI"
    assert body["fields"]["admission_date"]["evidence"] == "Поступил 01.03.2022"
    assert "Сидоров" not in body["anon_text"] and "[ФИО]" in body["anon_text"]

    assert c.get(f"/api/results/{body['id']}").json()["json"] == body["json"]
    download = c.get(f"/api/results/{body['id']}/download")
    assert download.json() == body["json"]
    assert "filename*=UTF-8''%D0%BF" in download.headers["content-disposition"]
    assert [d["id"] for d in c.get("/api/documents").json()] == [body["id"]]
    assert c.get("/").status_code == 200
    assert c.get("/inspect").status_code == 200
    assert c.get("/img/open2.webp").headers["content-type"] == "image/webp"


def test_rejects_bad_files():
    c = client()
    assert c.post("/api/extract", files={"file": ("a.pdf", b"%PDF", "application/pdf")}).json()["detail"] == \
        "unsupported_extension"
    assert c.post("/api/extract", files={"file": ("a.md", b"  ", "text/markdown")}).status_code == 400
    assert c.get("/api/results/missing").status_code == 404


def test_browser_entry_matches_api():
    import json

    from app import browser

    api = client().post("/api/extract", files={"file": ("пациент-1.md", DOC.encode("cp1251"), "text/markdown")}).json()
    local = json.loads(browser.extract(DOC.encode("cp1251"), "пациент-1.md"))
    same = ("filename", "doc_id", "sha256", "anon_text", "warnings", "pipeline_version", "json", "fields")
    assert {k: local[k] for k in same} == {k: api[k] for k in same}
    assert json.loads(browser.extract(b"%PDF", "a.pdf")) == {"detail": "unsupported_extension"}
    assert json.loads(browser.schema())["mode"] == "browser"
    assert client().get("/api.js").status_code == 200
