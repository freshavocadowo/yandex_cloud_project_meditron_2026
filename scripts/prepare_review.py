"""Create two developer reference fixtures from manually read source documents.

These are regression references, not expert annotations or organizer ground truth.
"""
import hashlib
import json
from pathlib import Path

from statchem.contract import TEMPLATE
from statchem.pipeline import write_json

COMMON = {"atr_fibril": "0", "copd": "0", "dm": "0", "ecg_avb": "0", "ecg_elevation": "1", "tlt": "0", "killip": "1", "ecg_rythm": "синусовый"}
REFERENCES = {
    "train-0001": {**COMMON, "admission_date": "01.01.2020", "discharge_date": "07.01.2020", "art_hyper": "1",
                   "diagnosis_icd": "I21.0", "mi_localisation": "A", "type_acs": "STEMI", "bp": "147/91", "bpm": "92",
                   "rr": "16", "spo2": "95", "ecg_bpm": "84", "rg_date": "01.01.2020", "ca_fact": "R", "card_trop": "положительный",
                   "crea": "99", "glu": "4.6", "hb": "116", "leucocytes": "9.9", "2_aag": "Клопидогрел 75 мг 1 раз в день",
                   "aspirin": "Ацетилсалициловая кислота 100 мг утром", "statin": "Аторвастатин 80 мг вечером"},
    "train-0002": {**COMMON, "admission_date": "12.08.2021", "discharge_date": "18.08.2021", "art_hyper": "0",
                   "diagnosis_icd": "I21.1", "hf": "ХСН 2А, ФК 2", "mi_localisation": "I", "type_acs": "STEMI", "bmi": "33.0",
                   "bp": "123/75", "bpm": "72", "height": "180", "rr": "16", "smoking": "Курит", "spo2": "95", "weight": "107",
                   "ecg_bpm": "110", "echo_ef": "53", "echo_lvd": "49", "echo_lvd_2": "37", "echo_mr": "Митральная регургитация 2 ст.",
                   "echo_zone": "Гипокинез нижней стенки ЛЖ", "rg_date": "12.08.2021", "ca_fact": "N", "card_trop": "положительный",
                   "crea": "75", "glu": "5.6", "hb": "116", "ldl": "2.4", "leucocytes": "6.4", "thrombocytes": "290", "tot_chol": "5.9",
                   "2_aag": "Клопидогрел 75 мг 1 раз в день", "ace_ing_sartan": "Периндоприл 5 мг утром",
                   "aspirin": "Ацетилсалициловая кислота 100 мг утром", "bb": "Метопролол 50 мг 2 раза в день", "statin": "Аторвастатин 80 мг вечером"},
}
for stem, values in REFERENCES.items():
    output = {g: {f: values.get(f, "не указано") for f in fs} for g, fs in TEMPLATE.items()}
    write_json(Path("tests/reference", stem + ".json"), output)

names = [p.stem for p in Path("participant-kit-realistic-v2-100/documents").glob("*.md") if p.stem not in REFERENCES]
ranked = sorted(names, key=lambda n: hashlib.sha256(("statchem-validation-42:" + n).encode()).hexdigest())
write_json(Path("config/validation-split.json"), {"seed": "statchem-validation-42", "validation": sorted(ranked[:20]), "development": sorted(set(names)-set(ranked[:20])) + sorted(REFERENCES), "note": "Prospective validation split; not an untouched holdout for the current MVP."})
