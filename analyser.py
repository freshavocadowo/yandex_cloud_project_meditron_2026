"""
Анализирует result/*.json и находит ЛОЖНЫЕ "не указано":
когда поле пустое, но маркер (С ДОЗОЙ, если препарат) ЕСТЬ в тексте.
"""

import json
import re
from pathlib import Path
from collections import Counter, defaultdict

RESULT_DIR = Path("result")
DATA_DIR   = Path("data/documents")

# ---------- Строгие маркеры (с дозой для препаратов) ----------
FIELD_HINTS = {
    # Диагнозы
    "diagnosis.art_hyper": r"Гипертоническая болезнь|ГБ II",
    "diagnosis.atr_fibril": r"Фибрилляция предсердий|Трепетание предсердий",
    "diagnosis.ckd": r"ХБП\s+\d",
    "diagnosis.copd": r"ХОБЛ",
    "diagnosis.dm": r"Сахарный диабет\s+\d",
    "diagnosis.hf": r"ХСН\s+\d",
    "diagnosis.killip": r"Killip",
    "diagnosis.tlt": r"тромболизис",

    # Осмотр
    "admission_exam.bmi": r"ИМТ\s+\d",
    "admission_exam.bp": r"АД\s+\d+/\d+",
    "admission_exam.bpm": r"пульс\s+\d+",
    "admission_exam.height": r"Рост\s+\d+",
    "admission_exam.rr": r"ЧДД\s+\d+",
    "admission_exam.smoking": r"Курит|Не курит|Бросил курить|Прекратила курить",
    "admission_exam.spo2": r"SpO2\s+\d+",
    "admission_exam.weight": r"масса тела\s+\d+",

    # ЭКГ
    "ecg.ecg_avb": r"АВ-блокада",
    "ecg.ecg_bpm": r"ЧСС\s+\d+",
    "ecg.ecg_elevation": r"Элевация ST|Подъём ST|Подъёма ST",
    "ecg.ecg_rythm": r"синусовый ритм|фибрилляция предсердий",

    # ЭхоКГ
    "echo.echo_ef": r"ФВ\s*ЛЖ\s+\d+",
    "echo.echo_lvd": r"КДР\s*ЛЖ\s+\d+",
    "echo.echo_lvd_2": r"ЛП\s+\d+",
    "echo.echo_mr": r"Митральная регургитация\s+\d",
    "echo.echo_zone": r"Гипокинез",

    # Рентген
    "xray.rg_date": r"Рентгенограмма|Рентгенография|Р-графия",
    "xray.rg_pc": r"венозн|отёк лёгк|интерстициальн|застой",

    # КАГ
    "coronary.ca_date": r"(?:Коронарография|КАГ)[^\d]{0,60}\d{2}\.\d{2}\.\d{4}",
    "coronary.ca_lad": r"ПМЖВ",
    "coronary.rca": r"ПКА",

    # Лабы
    "labs.card_trop": r"тропониновый тест",
    "labs.crea": r"креатинин\s+\d",
    "labs.glu": r"глюкоза\s+\d",
    "labs.hb": r"гемоглобин\s+\d",
    "labs.ldl": r"ХС-ЛПНП\s+\d",
    "labs.leucocytes": r"лейкоциты\s+\d",
    "labs.thrombocytes": r"тромбоциты\s+\d",
    "labs.tot_chol": r"общий холестерин\s+\d",

    # Препараты — ТОЛЬКО с дозой
    "meds.2_aag": r"(?:^|[\s\d.])(Клопидогрел|Тикагрелор)\s+\d+\s*мг",
    "meds.ace_ing_sartan": r"(?:^|[\s\d.])(Периндоприл|Рамиприл|Лозартан)\s+\d+\s*мг",
    "meds.anticoagulant": r"(?:^|[\s\d.])(Апиксабан|Ривароксабан)\s+\d+\s*мг",
    "meds.aspirin": r"(?:^|[\s\d.])(Ацетилсалициловая кислота|АСК|Аспирин)\s+\d+\s*мг",
    "meds.bb": r"(?:^|[\s\d.])(Бисопролол|Метопролол)\s+\d+\s*мг",
    "meds.statin": r"(?:^|[\s\d.])(Аторвастатин|Розувастатин)\s+\d+\s*мг",
}

# ---------- Сбор статистики ----------
counter = Counter()
false_negatives = defaultdict(list)
true_negatives = Counter()

result_files = sorted(RESULT_DIR.glob("train-*.json"))
print(f"📄 Найдено JSON: {len(result_files)}\n")

for jf in result_files:
    data = json.loads(jf.read_text(encoding="utf-8"))
    stem = jf.stem
    md_file = DATA_DIR / f"{stem}.md"
    if not md_file.exists():
        continue
    text = md_file.read_text(encoding="utf-8")

    for group, fields in data.items():
        for key, val in fields.items():
            full_key = f"{group}.{key}"
            if val != "не указано":
                continue
            counter[full_key] += 1

            # Пропуск ca_date при ca_fact = N/R
            if full_key == "coronary.ca_date":
                ca_fact = data.get("coronary", {}).get("ca_fact")
                if ca_fact in ("N", "R"):
                    true_negatives[full_key] += 1
                    continue

            hint = FIELD_HINTS.get(full_key)
            if not hint:
                continue
            m = re.search(hint, text, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 50)
                end = min(len(text), m.end() + 80)
                snippet = text[start:end].replace("\n", " ")
                false_negatives[full_key].append((stem, snippet))
            else:
                true_negatives[full_key] += 1

# ---------- ТОП-20 ----------
print("📊 ТОП-20 полей с «не указано»:\n")
print(f"{'Поле':<35} {'Всего':<8} {'Ложных':<8} {'Истинных'}")
print("-" * 80)
for field, count in counter.most_common(20):
    fn = len(false_negatives.get(field, []))
    tn = true_negatives.get(field, 0)
    flag = "🔴" if fn > 5 else ("⚠️" if fn > 0 else "✅")
    print(f"{flag} {field:<33} {count}/100   {fn:<8} {tn}")

# ---------- Ложные "не указано" ----------
print("\n" + "=" * 80)
print("🔴 ЛОЖНЫЕ «не указано» — маркер есть, но поле пустое")
print("=" * 80)

if not false_negatives:
    print("\n✅ Ложных «не указано» НЕ НАЙДЕНО")
else:
    for field, items in sorted(false_negatives.items(), key=lambda x: -len(x[1])):
        print(f"\n🔸 {field} — {len(items)} файлов")
        for stem, snippet in items[:3]:
            print(f"   {stem}.md: ...{snippet}...")

print("\n✅ Готово.")