"""
Валидатор JSON-файлов по контракту кейса.
Проверяет:
1. Наличие 9 групп
2. Наличие всех 50 ключей
3. Типы значений (0/1, числа-строки, даты ДД.ММ.ГГГГ, «не указано»)
4. Формат bp = «верхнее/нижнее»
5. Формат echo_mr = полная фраза
6. Формат ckd = «ХБП <стадия>»
7. Логику ca_fact (Y/R/N) → ca_lad/rca = «не указано» если N/R
8. Соответствие примеров из кейса (echo_rythm = «синусовый» без слова «ритм»)
"""

import json
import re
from pathlib import Path
from collections import Counter

RESULT_DIR = Path("result")

# ================== КОНТРАКТ ==================
# 9 групп и их ключи
CONTRACT = {
    "episode_dates": ["admission_date", "discharge_date"],
    "diagnosis": [
        "art_hyper", "atr_fibril", "ckd", "copd", "diagnosis_icd",
        "dm", "hf", "killip", "mi_localisation", "tlt", "type_acs",
    ],
    "admission_exam": [
        "bmi", "bp", "bpm", "height", "rr", "smoking", "spo2", "weight",
    ],
    "ecg": ["ecg_avb", "ecg_bpm", "ecg_elevation", "ecg_rythm"],
    "echo": ["echo_ef", "echo_lvd", "echo_lvd_2", "echo_mr", "echo_zone"],
    "xray": ["rg_date", "rg_pc"],
    "coronary": ["ca_date", "ca_fact", "ca_lad", "rca"],
    "labs": [
        "card_trop", "crea", "glu", "hb",
        "ldl", "leucocytes", "thrombocytes", "tot_chol",
    ],
    "meds": [
        "2_aag", "ace_ing_sartan", "anticoagulant",
        "aspirin", "bb", "statin",
    ],
}

# ================== ТИПЫ ПОЛЕЙ ==================
BINARY = {"art_hyper", "atr_fibril", "copd", "dm", "tlt", "ecg_avb", "ecg_elevation"}
NUMERIC = {
    "bmi", "bpm", "height", "rr", "spo2", "weight",
    "ecg_bpm", "echo_ef", "echo_lvd", "echo_lvd_2",
    "crea", "glu", "hb", "ldl", "leucocytes", "thrombocytes", "tot_chol",
}
SCALE = {"ca_lad", "rca"}                # 0/1/2
DATE = {"admission_date", "discharge_date", "rg_date", "ca_date"}
DRUG = {"2_aag", "ace_ing_sartan", "anticoagulant", "aspirin", "bb", "statin"}
SPECIAL = {"bp"}                         # «верхнее/нижнее»
KILLIP = {"killip"}                      # 1/2/3/4
CATEG = {
    "ckd", "hf", "mi_localisation", "type_acs",
    "ecg_rythm", "echo_mr", "echo_zone", "rg_pc",
    "ca_fact", "smoking", "card_trop", "diagnosis_icd",
}


# ================== ПРОВЕРКИ ==================
def check_structure(data: dict) -> list:
    """Проверка 9 групп и 50 ключей."""
    problems = []
    for group, keys in CONTRACT.items():
        if group not in data:
            problems.append(f"❌ Отсутствует группа: {group}")
            continue
        for key in keys:
            if key not in data[group]:
                problems.append(f"❌ Отсутствует ключ: {group}.{key}")
    return problems


def check_extra_keys(data: dict) -> list:
    """Проверка на лишние ключи/группы."""
    problems = []
    for group in data:
        if group not in CONTRACT:
            problems.append(f"⚠️ Лишняя группа: {group}")
            continue
        for key in data[group]:
            if key not in CONTRACT[group]:
                problems.append(f"⚠️ Лишний ключ: {group}.{key}")
    return problems


def check_types(data: dict) -> list:
    """Проверка типов значений."""
    problems = []

    for group, keys in CONTRACT.items():
        if group not in data:
            continue
        for key in keys:
            val = data[group].get(key, None)
            if val is None:
                continue

            full_key = f"{group}.{key}"

            # --- BINARY: 0 или 1 ---
            if key in BINARY:
                if val not in (0, 1, "0", "1"):
                    problems.append(f"❌ {full_key}: ожидалось 0/1, получено {val!r}")

            # --- NUMERIC: число или «не указано» ---
            elif key in NUMERIC:
                if val != "не указано":
                    try:
                        float(val)
                    except (ValueError, TypeError):
                        problems.append(f"❌ {full_key}: ожидалось число/«не указано», получено {val!r}")

            # --- SCALE: 0/1/2 или «не указано» ---
            elif key in SCALE:
                if val not in (0, 1, 2, "0", "1", "2", "не указано"):
                    problems.append(f"❌ {full_key}: ожидалось 0/1/2/«не указано», получено {val!r}")

            # --- DATE: ДД.ММ.ГГГГ или «не указано» ---
            elif key in DATE:
                if val != "не указано" and not re.match(r"^\d{2}\.\d{2}\.\d{4}$", str(val)):
                    problems.append(f"❌ {full_key}: ожидалось ДД.ММ.ГГГГ, получено {val!r}")

            # --- BP: «верхнее/нижнее» ---
            elif key in SPECIAL:
                if val != "не указано" and not re.match(r"^\d{2,3}/\d{2,3}$", str(val)):
                    problems.append(f"❌ {full_key}: ожидалось «верхнее/нижнее», получено {val!r}")

            # --- KILLIP: 1/2/3/4 или «не указано» ---
            elif key in KILLIP:
                if val not in (1, 2, 3, 4, "1", "2", "3", "4", "не указано"):
                    problems.append(f"❌ {full_key}: ожидалось 1/2/3/4/«не указано», получено {val!r}")

            # --- DRUG: непустая строка с дозой ---
            elif key in DRUG:
                if val == "не указано":
                    continue
                if not isinstance(val, str):
                    problems.append(f"❌ {full_key}: ожидалась строка, получено {val!r}")
                    continue
                if not re.search(r"\d+\s*мг", val):
                    problems.append(f"❌ {full_key}: нет дозы «мг» в {val!r}")

            # --- CATEG: непустая строка ---
            elif key in CATEG:
                if not isinstance(val, str):
                    problems.append(f"❌ {full_key}: ожидалась строка, получено {val!r}")

    return problems


def check_special_rules(data: dict) -> list:
    """Проверка специфичных правил кейса."""
    problems = []

    # --- echo_mr: полная фраза «Митральная регургитация X ст.» ---
    mr = data.get("echo", {}).get("echo_mr", "не указано")
    if mr != "не указано":
        if not re.match(r"^Митральная регургитация\s+\d+\s*ст\.?", mr):
            problems.append(f"❌ echo.echo_mr: ожидалось «Митральная регургитация N ст.», получено {mr!r}")

    # --- ckd: с префиксом «ХБП» ---
    ckd = data.get("diagnosis", {}).get("ckd", "не указано")
    if ckd != "не указано":
        if not re.match(r"^ХБП\s+", ckd):
            problems.append(f"❌ diagnosis.ckd: ожидалось «ХБП <стадия>», получено {ckd!r}")

    # --- ecg_rythm: «синусовый» без слова «ритм» ---
    rhythm = data.get("ecg", {}).get("ecg_rythm", "не указано")
    if rhythm == "синусовый ритм":
        problems.append(f"⚠️ ecg.ecg_rythm: ожидалось «синусовый», получено «синусовый ритм»")

    # --- ca_fact и ca_lad/rca ---
    ca_fact = data.get("coronary", {}).get("ca_fact", "N")
    ca_lad = data.get("coronary", {}).get("ca_lad", "не указано")
    rca = data.get("coronary", {}).get("rca", "не указано")

    if ca_fact in ("N", "R"):
        if ca_lad != "не указано":
            problems.append(f"❌ coronary.ca_lad: при ca_fact={ca_fact} ожидалось «не указано», получено {ca_lad!r}")
        if rca != "не указано":
            problems.append(f"❌ coronary.rca: при ca_fact={ca_fact} ожидалось «не указано», получено {rca!r}")

    if ca_fact == "Y":
        if ca_lad == "не указано":
            problems.append(f"⚠️ coronary.ca_lad: при ca_fact=Y ожидалось 0/1/2, получено «не указано»")
        if rca == "не указано":
            problems.append(f"⚠️ coronary.rca: при ca_fact=Y ожидалось 0/1/2, получено «не указано»")

    # --- ca_date при ca_fact=N/R ---
    ca_date = data.get("coronary", {}).get("ca_date", "не указано")
    if ca_fact in ("N", "R") and ca_date != "не указано":
        problems.append(f"❌ coronary.ca_date: при ca_fact={ca_fact} ожидалось «не указано», получено {ca_date!r}")

    return problems


# ================== ГЛАВНЫЙ ЦИКЛ ==================
def main():
    if not RESULT_DIR.exists():
        print(f"❌ Папка {RESULT_DIR} не найдена")
        return

    json_files = sorted(RESULT_DIR.glob("train-*.json"))
    print(f"📄 Найдено JSON: {len(json_files)}\n")

    all_problems = {}
    problem_counter = Counter()

    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            all_problems[jf.stem] = [f"❌ Невалидный JSON: {e}"]
            continue

        problems = []
        problems += check_structure(data)
        problems += check_extra_keys(data)
        problems += check_types(data)
        problems += check_special_rules(data)

        if problems:
            all_problems[jf.stem] = problems
            for p in problems:
                kind = p.split(":")[0].strip()
                problem_counter[kind] += 1

    # ---- Итоги ----
    print("=" * 80)
    print("📊 ИТОГИ ВАЛИДАЦИИ")
    print("=" * 80)

    if not all_problems:
        print("\n✅ ВСЕ 100 ФАЙЛОВ ПРОШЛИ ВАЛИДАЦИЮ")
        print("   Структура, типы и специальные правила соблюдены.")
        return

    print(f"\n⚠️ Файлов с проблемами: {len(all_problems)} / {len(json_files)}\n")

    print("📈 ТОП типов проблем:")
    for kind, count in problem_counter.most_common(15):
        print(f"  {kind}: {count}")

    print("\n" + "=" * 80)
    print("🔍 ДЕТАЛИ ПО ФАЙЛАМ (первые 5)")
    print("=" * 80)

    for stem, probs in list(all_problems.items())[:5]:
        print(f"\n🔸 {stem}.json — {len(probs)} проблем:")
        for p in probs[:10]:
            print(f"   {p}")
        if len(probs) > 10:
            print(f"   ... и ещё {len(probs) - 10}")

    print("\n" + "=" * 80)
    print("📋 СВОДКА ПО ПОЛЯМ (что чаще всего ломается)")
    print("=" * 80)

    field_counter = Counter()
    for probs in all_problems.values():
        for p in probs:
            m = re.search(r"([a-z_]+\.[a-z_0-9]+)", p)
            if m:
                field_counter[m.group(1)] += 1

    if field_counter:
        for field, count in field_counter.most_common(20):
            print(f"  {field}: {count} файлов")
    else:
        print("  (не удалось извлечь поля)")


if __name__ == "__main__":
    main()