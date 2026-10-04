import json
from pathlib import Path

from app import batch
from app.anonymize import TOKENS
from app.extract import Finding
from app.extract.llm import LLMError, fill_missing
from app.ingest import load_path
from app.pipeline import process
from app.schema import FIELDS, GROUPS, empty, validate
from eval.score import score

from conftest import CORPUS

GOLD = Path(__file__).resolve().parents[1] / "eval" / "gold"
TEMPLATE = CORPUS.parent / "participant-output-template-50.json"


def test_schema_matches_template():
    assert sum(map(len, GROUPS.values())) == 50
    if TEMPLATE.is_file():
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        assert list(template) == list(GROUPS)
        assert {g: list(v) for g, v in template.items()} == {g: list(v) for g, v in GROUPS.items()}
    assert validate(empty()) == []


def test_validate_rejects_contract_violations():
    broken = empty()
    broken["ЭКГ"]["ecg_avb"] = "да"
    broken["даты эпизода"]["admission_date"] = "2021-09-10"
    broken["диагноз"].pop("killip")
    broken["лишнее"] = {}
    assert set(validate(broken)) == {"not_in_enum:ecg_avb", "bad_format:admission_date", "missing_key:killip",
                                     "extra_group:лишнее"}


def test_corpus_results_are_valid_and_evidenced(corpus):
    for path in corpus:
        extraction = process(load_path(path))
        assert validate(extraction.result) == [], path.name
        for key, f in extraction.findings.items():
            if f.source != "default":
                assert extraction.anon_text[f.start:f.end] == f.evidence, (path.name, key)
        # В цитаты попадает только обезличенный текст: токены масок не подменяются данными.
        assert not any(t in f.value for f in extraction.findings.values() for t in TOKENS.values())


def test_batch_writes_every_file_and_matches_gold(corpus, tmp_path):
    summary = batch.run(CORPUS, tmp_path / "result", tmp_path / "evidence", workers=4, log_dir=tmp_path / "logs")
    assert summary["failed"] == 0 and summary["ok"] == len(corpus)
    assert sorted(p.stem for p in (tmp_path / "result").glob("*.json")) == sorted(p.stem for p in corpus)
    again = batch.run(CORPUS, tmp_path / "result", tmp_path / "evidence", workers=4, log_dir=tmp_path / "logs")
    assert again["cached"] == len(corpus)  # кэш по sha256 + версии конвейера
    report = score(tmp_path / "result", [p.stem for p in corpus], GOLD, tmp_path / "evidence")
    assert report["valid_json"] == 1 and report["evidence_rate"] == 1
    assert report["accuracy"] == 1, report["mismatches"]


def test_batch_writes_template_for_unreadable_file(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "empty.md").write_text("   \n", encoding="utf-8")
    summary = batch.run(docs, tmp_path / "result", tmp_path / "evidence", log_dir=tmp_path / "logs")
    assert summary["failed"] == 1
    assert json.loads((tmp_path / "result" / "empty.json").read_text(encoding="utf-8")) == empty()
    assert "empty,empty_document" in (tmp_path / "logs" / "failed.csv").read_text(encoding="utf-8")


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def chat(self, messages, schema):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return json.dumps(answer, ensure_ascii=False)


TEXT = "Анамнез: курит 20 лет. Гипертоническая болезнь III стадии."


def defaults() -> dict:
    return {key: Finding("0" if key == "art_hyper" else "не указано", source="default") for key in ("smoking", "art_hyper")}


def test_llm_fills_only_missing_fields_with_verified_evidence():
    llm = FakeLLM({"smoking": {"value": "Курит", "evidence": "курит 20 лет"},
                   "art_hyper": {"value": "1", "evidence": "Гипертоническая болезнь III стадии"}})
    found, warnings = fill_missing(llm, TEXT, defaults())
    assert warnings == [] and found["smoking"].source == "llm"
    assert TEXT[found["art_hyper"].start:found["art_hyper"].end] == "Гипертоническая болезнь III стадии"


def test_llm_hallucinated_evidence_is_retried_then_dropped():
    bad = {"smoking": {"value": "Не курит", "evidence": "никогда не курил"}, "art_hyper": {"value": "1", "evidence": ""}}
    llm = FakeLLM(bad, bad, bad)
    found, warnings = fill_missing(llm, TEXT, defaults())
    assert llm.calls == 3 and warnings == ["llm_partial"]
    assert found["smoking"].source == "default" and found["art_hyper"].source == "default"


def test_llm_unavailable_falls_back_to_rules():
    found, warnings = fill_missing(FakeLLM(LLMError("URLError")), TEXT, defaults())
    assert warnings == ["llm_unavailable:URLError"] and found == defaults()


def test_all_fields_present_in_findings(corpus):
    assert list(process(load_path(corpus[0])).findings) == list(FIELDS)
