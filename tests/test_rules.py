"""Правила на вариантах формулировок, которых нет в 100 открытых документах (запас на контрольную выборку)."""
from app.ingest import load_bytes
from app.pipeline import process
from app.schema import NOT_FOUND


def extract(text: str) -> dict:
    extraction = process(load_bytes(text.encode(), "doc.md"))
    for f in extraction.findings.values():  # цитата — ровно фрагмент обезличенного текста
        if f.source != "default":
            assert extraction.anon_text[f.start:f.end] == f.evidence
    return {key: f.value for key, f in extraction.findings.items()}


def test_dates_variants():
    v = extract("ЭПИКРИЗ\nДата поступления: 10 сентября 2021 г. Дата выписки: 16/09/21.\n")
    assert (v["admission_date"], v["discharge_date"]) == ("10.09.2021", "16.09.2021")
    v = extract("ЭПИКРИЗ\nПациент: Иван Петров. Период лечения: с 01.02.2022 по 09.02.2022.\n")
    assert (v["admission_date"], v["discharge_date"]) == ("01.02.2022", "09.02.2022")


def test_diagnosis_variants():
    v = extract("ЭПИКРИЗ\n\nДиагноз:\nОсновной: Острый переднебоковой инфаркт миокарда с подъёмом сегмента ST "
                "(МКБ-10: I21.0). Killip класс III.\nСопутствующие: ХСН IIА ст., ФК III; хроническая болезнь почек "
                "3а стадии; ХОБЛ. Сахарный диабет отрицает. Трепетание предсердий.\n")
    assert v["diagnosis_icd"] == "I21.0"
    assert v["killip"] == "3"
    assert v["type_acs"] == "STEMI" and v["mi_localisation"] == "A"
    assert v["hf"] == "ХСН 2А, ФК 3"
    assert v["ckd"] == "ХБП 3А"
    assert (v["copd"], v["dm"], v["atr_fibril"], v["art_hyper"]) == ("1", "0", "1", "0")


def test_acs_type_without_st_wording_uses_icd():
    v = extract("ЭПИКРИЗ\n\nДиагноз:\nОИМ. Код МКБ-10 I21.4.\n")
    assert (v["type_acs"], v["mi_localisation"]) == ("NSTEMI", "N")
    v = extract("ЭПИКРИЗ\n\nДиагноз:\nИБС: нестабильная стенокардия. Код МКБ-10 I20.0.\n")
    assert (v["type_acs"], v["mi_localisation"]) == ("NA", NOT_FOUND)


def test_thrombolysis_negation():
    assert extract("ЭПИКРИЗ\n\nЛечение:\nТромболизис не проводился.\n")["tlt"] == "0"
    assert extract("ЭПИКРИЗ\n\nЛечение:\nВыполнена ТЛТ алтеплазой.\n")["tlt"] == "1"


def test_exam_takes_primary_measurement():
    v = extract("ЭПИКРИЗ\n\nОбъективно:\nАД: 150/95 мм рт.ст., ЧСС 88 уд/мин, ЧДД 20, сатурация 93 %. "
                "Рост 175 см, вес 80,5 кг, индекс массы тела 26,3. Не курит.\n\n"
                "Состояние в динамике:\n12.01.2022. АД 120/80 мм рт. ст., пульс 70 в минуту.\n")
    assert (v["bp"], v["bpm"], v["rr"], v["spo2"]) == ("150/95", "88", "20", "93")
    assert (v["height"], v["weight"], v["bmi"], v["smoking"]) == ("175", "80.5", "26.3", "Не курит")


def test_ecg_first_record_only():
    v = extract("ЭПИКРИЗ\n\nЭКГ:\nРитм синусовый, ЧСС 79 уд/мин. Подъём ST в II, III, aVF. АВ-блокада I ст.\n"
                "Контрольная ЭКГ: ЧСС 60 уд/мин, ритм синусовый.\n")
    assert (v["ecg_rythm"], v["ecg_bpm"], v["ecg_elevation"], v["ecg_avb"]) == ("синусовый", "79", "1", "1")
    v = extract("ЭПИКРИЗ\n\nЭКГ:\nФибрилляция предсердий, ЧСС 112 уд/мин. Подъёма ST не зарегистрировано.\n")
    assert (v["ecg_rythm"], v["ecg_elevation"], v["atr_fibril"]) == ("фибрилляция предсердий", "0", "1")


def test_echo_and_xray():
    v = extract("ЭПИКРИЗ\n\nЭхоКГ:\nФВ (Симпсон) 38%, КДР ЛЖ 58 мм, ЛП 45 мм. Акинез верхушки и передней стенки "
                "левого желудочка. Митральная регургитация 1 ст. Выпота нет.\n\n"
                "Рентгенография ОГК:\nОт 03.03.2022. Признаков застоя нет.\n")
    assert (v["echo_ef"], v["echo_lvd"], v["echo_lvd_2"]) == ("38", "58", "45")
    assert v["echo_zone"] == "Акинез верхушки и передней стенки"
    assert v["echo_mr"] == "Митральная регургитация 1 ст."
    assert (v["rg_date"], v["rg_pc"]) == ("03.03.2022", NOT_FOUND)


def test_coronary_angiography_grades():
    v = extract("ЭПИКРИЗ\n\nКоронароангиография:\n05.05.2022 выполнена КАГ. ПМЖВ: стеноз 70%; ПКА: стеноз 40%.\n")
    assert (v["ca_fact"], v["ca_date"], v["ca_lad"], v["rca"]) == ("Y", "05.05.2022", "1", "0")
    v = extract("ЭПИКРИЗ\n\nКАГ:\nОт коронарографии пациент отказался.\n")
    assert (v["ca_fact"], v["ca_date"], v["ca_lad"], v["rca"]) == ("R", NOT_FOUND, NOT_FOUND, NOT_FOUND)
    assert extract("ЭПИКРИЗ\n\nЖалобы:\nБоли за грудиной.\n")["ca_fact"] == "N"


def test_labs_first_value_and_troponin_number():
    v = extract("ЭПИКРИЗ\n\nЛабораторные данные:\nКреатинин от 01.02.2022: 98 мкмоль/л; Hb 141 г/л; "
                "тропонин I 0,05 нг/мл; ОХС 5,4; ЛПНП 3,1 ммоль/л; WBC 7,0; PLT 250; глюкоза 6,1.\n"
                "Контроль: креатинин 120 мкмоль/л.\n")
    assert (v["crea"], v["hb"], v["card_trop"]) == ("98", "141", "0.05")
    assert (v["tot_chol"], v["ldl"], v["leucocytes"], v["thrombocytes"], v["glu"]) == ("5.4", "3.1", "7.0", "250", "6.1")


def test_discharge_drugs_inline_and_negated():
    v = extract("ЭПИКРИЗ\n\nРекомендации:\nБисопролол 2,5 мг утром; аторвастатин 40 мг вечером; валсартан 80 мг; "
                "тикагрелор 90 мг 2 раза в день. Аспирин отменён из-за кровотечения.\n")
    assert v["bb"] == "Бисопролол 2,5 мг утром"
    assert v["statin"] == "Аторвастатин 40 мг вечером"
    assert v["ace_ing_sartan"] == "Валсартан 80 мг"
    assert v["2_aag"] == "Тикагрелор 90 мг 2 раза в день"
    assert v["aspirin"] == NOT_FOUND


def test_document_without_headings_uses_fallback():
    v = extract("Выписка. Поступил 02.03.2023, выписан 09.03.2023. ИБС: острый нижний инфаркт миокарда с подъёмом ST. "
                "АД 130/80, пульс 76. На ЭКГ синусовый ритм, ЧСС 74.\n")
    assert (v["admission_date"], v["discharge_date"], v["bp"]) == ("02.03.2023", "09.03.2023", "130/80")
    assert (v["type_acs"], v["mi_localisation"], v["ecg_bpm"]) == ("STEMI", "I", "74")
