import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from statchem.contract import FIELDS, Output, SCHEMA, TEMPLATE
from statchem.parser import parse
from statchem.pipeline import batch, process, verify_candidate
from statchem.privacy import anonymize
from statchem.rules import extract
from statchem.settings import Settings
from statchem.yandex import Candidate, Extraction

CORPUS = Path("participant-kit-realistic-v2-100/documents")


def local(text):
    return process(text, Settings(STATCHEM_USE_NER=False))


def flat(result):
    return {f: v for group in result.output.values() for f, v in group.items()}


def test_exact_contract():
    actual = json.loads(Path("participant-kit-realistic-v2-100/participant-output-template-50.json").read_text(encoding="utf-8"))
    assert TEMPLATE == actual
    assert len(TEMPLATE) == 9 and len(FIELDS) == 50
    value = local("Диагноз:\nСведений нет.").output
    Draft202012Validator(SCHEMA).validate(value)
    value["диагноз"]["dm"] = 1
    with pytest.raises(ValidationError):
        Output.model_validate(value)
    value["диагноз"]["dm"] = "0"
    value["unexpected"] = {}
    with pytest.raises(ValidationError):
        Output.model_validate(value)


def test_first_document_traps():
    r = local((CORPUS / "train-0001.md").read_text(encoding="utf-8"))
    v = flat(r)
    assert v["bpm"] == "92" and v["ecg_bpm"] == "84"
    assert v["crea"] == "99" and v["ca_fact"] == "R"
    assert v["smoking"] == "не указано" and v["card_trop"] == "положительный"
    assert v["bmi"] == "не указано" and v["mi_localisation"] == "A"
    assert [(x["value"],x["selected"]) for x in r.report["laboratory_observations"] if x["field"] == "crea"] == [("99", True), ("103", False)]
    for e in r.report["evidence"].values():
        if e["quote"]:
            assert r.masked_text[e["start"]:e["end"]] == e["quote"]


def test_hf_not_cancelled_and_no_angiography():
    v = flat(local((CORPUS / "train-0002.md").read_text(encoding="utf-8")))
    assert v["hf"] == "ХСН 2А, ФК 2"
    assert v["ca_fact"] == "N"
    assert v["ca_lad"] == v["rca"] == "не указано"
    assert v["smoking"] == "Курит"
    assert v["bmi"] == "33.0"
    assert v["echo_lvd"] == "49" and v["echo_lvd_2"] == "37"
    assert v["echo_mr"] == "Митральная регургитация 2 ст."


def test_inline_sections_and_period_dates():
    v = flat(local((CORPUS / "train-0003.md").read_text(encoding="utf-8")))
    assert v["admission_date"] == "23.03.2022" and v["discharge_date"] == "01.04.2022"
    assert v["crea"] == "80" and v["ca_fact"] == "Y" and v["ca_date"] == "25.03.2022"


def test_ner_preserves_medical_headings():
    r = process((CORPUS / "train-0100.md").read_text(encoding="utf-8"), Settings())
    v = flat(r)
    assert v["echo_ef"] == "47" and v["ca_lad"] == "2" and v["rca"] == "1"
    assert "Эхокардиография" in r.masked_text


@pytest.mark.parametrize("percent,expected", [(0, "0"), (49,"0"), (50,"1"), (89,"1"), (90,"2"), (100,"2")])
def test_vessel_boundaries(percent, expected):
    v = flat(local(f"КАГ:\nКоронарография от 01.01.2024: ПМЖВ: стеноз {percent}%; ПКА: окклюзия."))
    assert v["ca_fact"] == "Y" and v["ca_lad"] == expected and v["rca"] == "2"


def test_explicit_negation_and_no_inference():
    v = flat(local("Диагноз:\nСахарный диабет отрицает. ХСН 2А, ФК 3.\nПервичный статус:\nАД 180/90. Глюкоза 12. Рост 180 см, вес 90 кг.\nЭКГ:\nЧСС 80. Элевации ST нет. АВ-блокада не выявлена.\nРекомендации:\nАторвастатин отменён. Курение исключить."))
    assert v["dm"] == v["art_hyper"] == v["ecg_elevation"] == v["ecg_avb"] == "0"
    assert v["hf"] == "ХСН 2А, ФК 3"
    assert v["bmi"] == v["statin"] == v["smoking"] == "не указано"


def test_markdown_table_coordinates():
    r = local("# Анализы крови\n| Показатель | Значение |\n| --- | --- |\n| Креатинин | 99,1 |\n\n# ЭКГ\nЧСС 84")
    assert flat(r)["crea"] == "99.1" and flat(r)["ecg_bpm"] == "84"
    assert r.report["markdown_tables"] == 1


def test_privacy_masked_values_and_offsets():
    text = "Пациент: Иван Иванович Иванов, д.р. 01.02.1970, возраст 54 года.\nИстория болезни № 12345.\nТелефон +7 (999) 123-45-67; email ivan@example.ru.\nАдрес: Москва, ул. Ленина, 1.\nПоступил 01.03.2024.\n"
    r = anonymize(text, use_ner=False)
    assert len(text) == len(r.text) and not r.residual
    for value in ["Иван", "01.02.1970", "54 года", "12345", "999", "example.ru", "Ленина"]:
        assert value not in r.text
    assert "01.03.2024" in r.text
    assert all("value" not in x for x in r.spans)


def test_ner_unlabelled_name():
    r = anonymize("С пациентом Иваном Ивановичем Петровым обсуждены назначения.", use_ner=True)
    assert "Петров" not in r.text and not r.residual


def test_cloud_blocks_without_ner_or_credentials():
    with pytest.raises(ValueError):
        process("Диагноз:\nИБС.", Settings(YANDEX_API_KEY="", YANDEX_FOLDER_ID=""), "yandex")
    with pytest.raises(ValueError):
        process("Диагноз:\nИБС.", Settings(YANDEX_API_KEY="dummy", YANDEX_FOLDER_ID="dummy", STATCHEM_USE_NER=False), "yandex")


def test_value_and_quote_validation():
    doc = parse("Анализы крови:\nКреатинин 99; контроль креатинин 103.")
    facts, _ = extract(doc)
    base = {"field": "crea", "value": "103", "quote": "Креатинин 99", "section": "labs", "context": "primary"}
    fact, error = verify_candidate(Candidate(**base), doc, facts)
    assert fact is None and "not_supported" in error
    base["value"] = "99"
    assert verify_candidate(Candidate(**base), doc, facts)[0].value == "99"
    base["quote"] = "несуществующая цитата"
    assert verify_candidate(Candidate(**base), doc, facts)[0] is None


def test_qualitative_stenosis_needs_review():
    r = local("КАГ:\nКоронарография от 01.01.2024: ПМЖВ: гемодинамически значимого стеноза нет; ПКА: стеноз до 40%.")
    assert flat(r)["ca_lad"] == "не указано" and flat(r)["rca"] == "0"
    assert "qualitative_stenosis_needs_review:ca_lad" in r.report["warnings"]


def test_model_cannot_hide_denial_by_shortening_quote():
    doc = parse("Диагноз:\nСахарный диабет отрицает.")
    candidate = Candidate(field="dm", value="1", quote="Сахарный диабет", section="diagnosis", context="diagnosis")
    fact, error = verify_candidate(candidate, doc, {})
    assert fact is None and error == "negation_in_source_context:dm"


def test_fake_cloud_only_receives_masked_text():
    class Fake:
        seen = None
        def extract(self, text, dictionary):
            self.seen = text
            return Extraction(candidates=[])
    fake = Fake()
    text = "Пациент: Иван Иванович Иванов, д.р. 01.01.1970.\nДиагноз:\nИБС."
    r = process(text, Settings(YANDEX_API_KEY="dummy", YANDEX_FOLDER_ID="dummy"), "yandex", fake)
    assert "Иван" not in fake.seen and "1970" not in fake.seen
    assert r.report["mode"] == "yandex"


def test_batch_failure_isolated_and_duplicate_flagged(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "train-0001.md").write_text("", encoding="utf-8")
    for name in ["train-0002", "train-0003"]:
        (inputs / (name + ".md")).write_text("Диагноз:\nСахарный диабет 2 типа.", encoding="utf-8")
    output = tmp_path / "result"
    output.mkdir()
    (output / "train-0001.json").write_text("stale", encoding="utf-8")
    s = batch(inputs, output, tmp_path / "reports", Settings(STATCHEM_USE_NER=False))
    assert s["failed"] == 1 and s["successful"] == 2
    assert not (output / "train-0001.json").exists()
    assert "duplicate_document" in s["items"][2]["warnings"]


def test_export_contains_no_identifiers():
    r = process((CORPUS / "train-0002.md").read_text(encoding="utf-8"), Settings())
    exported = json.dumps(r.report, ensure_ascii=False) + r.masked_text + json.dumps(r.output, ensure_ascii=False)
    for token in ["Марксова", "14.09.1867", "153 года", "700002"]:
        assert token not in exported
