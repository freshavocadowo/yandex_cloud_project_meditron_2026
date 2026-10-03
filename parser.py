import json
import re
from pathlib import Path
from collections import Counter

# ---------- Пути ----------
DATA_DIR   = Path("data/documents")
RESULT_DIR = Path("result")
DICT_DIR   = Path("dictionaries")

DEBUG = False

# ---------- Загрузка словарей ----------
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

SECTIONS = load_json(DICT_DIR / "sections.json")
MARKERS  = load_json(DICT_DIR / "markers.json")


# ---------- Segmenter ----------
def segment(text: str) -> dict:
    hits = []
    for section, headers in SECTIONS.items():
        for h in headers:
            for m in re.finditer(rf"(?im)^{re.escape(h)}[^\n]*$", text):
                hits.append((m.start(), section))

    hits.sort(key=lambda x: x[0])
    sections = {}
    for i, (pos, name) in enumerate(hits):
        end = hits[i+1][0] if i+1 < len(hits) else len(text)
        chunk = text[pos:end]
        sections[name] = sections.get(name, "") + "\n" + chunk
    return sections


# ---------- Helpers ----------
def clean_number(s: str) -> str:
    return s.replace(",", ".").strip()


def classify_stenosis(text: str):
    low = text.lower()
    if "окклюзия" in low:
        return 2
    m = re.search(r"стеноз\s+(\d{1,3})\s*%", low)
    if m:
        pct = int(m.group(1))
        return 2 if pct >= 90 else 1 if pct >= 50 else 0
    if "значимого стеноза нет" in low:
        return 0
    return "не указано"


def apply_map(value, mapping):
    if isinstance(mapping, dict):
        return mapping.get(value, value)
    if isinstance(mapping, list):
        for rule in mapping:
            if re.search(rule["pattern"], value, re.IGNORECASE):
                return rule["value"]
    return value


def has_negation_near(text: str, marker: str, negation_words, window=50) -> bool:
    for m in re.finditer(rf"(?i){re.escape(marker)}", text):
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        ctx = text[start:end].lower()
        if any(neg.lower() in ctx for neg in negation_words):
            return True
    return False


# ---------- Rules ----------
def extract_field(field: str, sections: dict, full_text: str):
    try:
        cfg = MARKERS.get(field)
        if not cfg:
            return "не указано"

        target_section = cfg.get("section")
        text = sections.get(target_section, "") if target_section else full_text
        if not text:
            text = full_text

        markers = cfg["markers"]
        ftype = cfg["type"]

        # ----- binary -----
        if ftype == "binary":
            found = any(re.search(rf"(?i){re.escape(m)}", text) for m in markers)
            if not found:
                return 0
            negation_words = cfg.get("negation", [])
            for mk in markers:
                if has_negation_near(text, mk, negation_words):
                    return 0
            return 1

        found = any(re.search(rf"(?i){re.escape(m)}", text) for m in markers)
        if not found:
            if "default_if_not_found" in cfg:
                return cfg["default_if_not_found"]
            return "не указано"

        # ----- numeric -----
        if ftype == "numeric":
            m = re.search(cfg["regex"], text, re.IGNORECASE)
            if not m:
                if DEBUG: print(f"  ⚠️ [{field}] regex не сработал")
                return "не указано"
            return clean_number(m.group(1))

        # ----- categorical -----
        if ftype == "categorical":
            # ФИКС: специальная обработка smoking с приоритетом
            if field == "smoking":
                priority = ["Не курит", "Бросил курить", "Прекратила курить", "Курит"]
                for mk in priority:
                    if re.search(rf"(?i){re.escape(mk)}", text):
                        return apply_map(mk, cfg.get("map", []))
                return "не указано"

            if "regex" in cfg:
                m = re.search(cfg["regex"], text, re.IGNORECASE)
                if not m:
                    if DEBUG: print(f"  ⚠️ [{field}] regex не сработал")
                    return "не указано"
                groups = m.groups()
                if "format" in cfg:
                    try:
                        return cfg["format"].format(*groups)
                    except Exception:
                        return "/".join(g for g in groups if g)
                val = groups[0]
                if "map" in cfg:
                    return apply_map(val, cfg["map"])
                return val
            for mk in markers:
                if re.search(rf"(?i){re.escape(mk)}", text):
                    if "map" in cfg:
                        return apply_map(mk, cfg["map"])
                    return mk
            return "не указано"

        # ----- code -----
        if ftype == "code":
            m = re.search(cfg["regex"], text)
            return m.group(1) if m else "не указано"

        # ----- date -----
        if ftype == "date":
            m = re.search(cfg["regex"], text)
            return m.group(1) if m else "не указано"

        # ----- date_near_marker -----
        if ftype == "date_near_marker":
            m = re.search(cfg["regex"], text, re.IGNORECASE)
            if not m:
                if DEBUG: print(f"  ⚠️ [{field}] дату не нашёл")
                return "не указано"
            for g in m.groups():
                if g:
                    return g
            return "не указано"

        # ----- date_in_section -----
        if ftype == "date_in_section":
            if target_section and target_section not in sections:
                if DEBUG: print(f"  ⚠️ [{field}] секции {target_section!r} нет")
                return "не указано"
            dates = re.findall(cfg["regex"], text)
            if not dates:
                if DEBUG: print(f"  ⚠️ [{field}] дат не нашёл")
                return "не указано"
            pick = cfg.get("pick", "first")
            return dates[-1] if pick == "last" else dates[0]

        # ----- scale (КАГ) -----
        if ftype == "scale":
            m = re.search(cfg["regex"], text, re.IGNORECASE)
            if not m:
                if DEBUG: print(f"  ⚠️ [{field}] regex не нашёл")
                return "не указано"
            raw = m.group(1).strip()
            if DEBUG: print(f"  🔍 [{field}] сырой фрагмент: {raw!r}")
            return classify_stenosis(raw)

        # ----- special (АД) -----
        if ftype == "special":
            m = re.search(cfg["regex"], text)
            if not m:
                return "не указано"
            groups = m.groups()
            if "format" in cfg:
                try:
                    return cfg["format"].format(*groups)
                except IndexError:
                    return "/".join(g for g in groups if g)
            return "/".join(g for g in groups if g)

        # ----- drug -----
        if ftype == "drug":
            if "drug_regex" in cfg:
                m = re.search(cfg["drug_regex"], text, re.IGNORECASE)
                if m:
                    return m.group(0).strip()
                return "не указано"
            for mk in markers:
                m = re.search(rf"(?i)(?:^|[\s\d.])({re.escape(mk)}[^\n]*)", text)
                if m:
                    return m.group(1).strip()
            return "не указано"

        return "не указано"

    except Exception as e:
        print(f"  ⚠️ Ошибка в поле {field}: {e}")
        return "не указано"


# ---------- Группировка ----------
GROUP_MAP = {
    "admission_date": "episode_dates", "discharge_date": "episode_dates",
    "art_hyper": "diagnosis", "atr_fibril": "diagnosis", "ckd": "diagnosis",
    "copd": "diagnosis", "diagnosis_icd": "diagnosis", "dm": "diagnosis",
    "hf": "diagnosis", "killip": "diagnosis", "mi_localisation": "diagnosis",
    "tlt": "diagnosis", "type_acs": "diagnosis",
    "bmi": "admission_exam", "bp": "admission_exam", "bpm": "admission_exam",
    "height": "admission_exam", "rr": "admission_exam", "smoking": "admission_exam",
    "spo2": "admission_exam", "weight": "admission_exam",
    "ecg_avb": "ecg", "ecg_bpm": "ecg", "ecg_elevation": "ecg", "ecg_rythm": "ecg",
    "echo_ef": "echo", "echo_lvd": "echo", "echo_lvd_2": "echo",
    "echo_mr": "echo", "echo_zone": "echo",
    "rg_date": "xray", "rg_pc": "xray",
    "ca_date": "coronary", "ca_fact": "coronary", "ca_lad": "coronary", "rca": "coronary",
    "card_trop": "labs", "crea": "labs", "glu": "labs", "hb": "labs",
    "ldl": "labs", "leucocytes": "labs", "thrombocytes": "labs", "tot_chol": "labs",
    "2_aag": "meds", "ace_ing_sartan": "meds", "anticoagulant": "meds",
    "aspirin": "meds", "bb": "meds", "statin": "meds",
}


# ---------- Валидатор ----------
def validate(result: dict) -> list:
    problems = []
    BINARY = {"art_hyper", "atr_fibril", "copd", "dm", "tlt", "ecg_avb", "ecg_elevation"}
    NUMERIC = {"bmi", "bpm", "height", "rr", "spo2", "weight",
               "ecg_bpm", "echo_ef", "echo_lvd", "echo_lvd_2",
               "crea", "glu", "hb", "ldl", "leucocytes", "thrombocytes", "tot_chol"}
    SCALE = {"ca_lad", "rca"}
    DATE = {"admission_date", "discharge_date", "rg_date", "ca_date"}

    for group, fields in result.items():
        for key, val in fields.items():
            if key == "bp":
                if val != "не указано" and not re.match(r"^\d{2,3}/\d{2,3}$", str(val)):
                    problems.append(f"{group}.{key}: ожидалось «верхнее/нижнее», получено {val!r}")
                continue
            if key in BINARY:
                if val not in (0, 1):
                    problems.append(f"{group}.{key}: ожидалось 0/1, получено {val!r}")
            elif key in NUMERIC:
                if val != "не указано":
                    try:
                        float(val)
                    except (ValueError, TypeError):
                        problems.append(f"{group}.{key}: ожидалось число/«не указано», получено {val!r}")
            elif key in SCALE:
                if val not in (0, 1, 2, "не указано"):
                    problems.append(f"{group}.{key}: ожидалось 0/1/2/«не указано», получено {val!r}")
            elif key in DATE:
                if val != "не указано" and not re.match(r"^\d{2}\.\d{2}\.\d{4}$", str(val)):
                    problems.append(f"{group}.{key}: ожидалось ДД.ММ.ГГГГ, получено {val!r}")
    return problems


# ---------- Парсинг одного эпикриза ----------
def parse_epicrisis(text: str) -> dict:
    sections = segment(text)
    result = {
        "episode_dates": {}, "diagnosis": {}, "admission_exam": {},
        "ecg": {}, "echo": {}, "xray": {}, "coronary": {},
        "labs": {}, "meds": {},
    }

    m_adm = re.search(
        r"(?:Поступил[а]?|Дата госпитализации|Период лечения:\s*с)\s*[:]?\s*(\d{2}\.\d{2}\.\d{4})",
        text, re.IGNORECASE,
    )
    m_dis = re.search(
        r"(?:Выписан[а]?|дата выписки|по)\s*[:]?\s*(\d{2}\.\d{2}\.\d{4})",
        text, re.IGNORECASE,
    )
    result["episode_dates"]["admission_date"] = m_adm.group(1) if m_adm else "не указано"
    result["episode_dates"]["discharge_date"] = m_dis.group(1) if m_dis else "не указано"

    for field, group in GROUP_MAP.items():
        if field in ("admission_date", "discharge_date"):
            continue
        result[group][field] = extract_field(field, sections, text)

    ca_fact = result["coronary"].get("ca_fact")
    if ca_fact in ("N", "R"):
        result["coronary"]["ca_date"] = "не указано"
        result["coronary"]["ca_lad"] = "не указано"
        result["coronary"]["rca"] = "не указано"

    return result


# ---------- Пакетная обработка ----------
def main():
    if not DATA_DIR.exists():
        print(f"❌ Папка {DATA_DIR} не найдена")
        return

    RESULT_DIR.mkdir(exist_ok=True)
    md_files = sorted(DATA_DIR.glob("train-*.md"))
    print(f"📄 Найдено {len(md_files)} документов\n")

    all_problems = {}
    empty_counter = Counter()

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        if DEBUG:
            print(f"\n=== {md_file.name} ===")
        parsed = parse_epicrisis(text)
        out_file = RESULT_DIR / f"{md_file.stem}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)

        problems = validate(parsed)
        if problems:
            all_problems[md_file.name] = problems

        for group, fields in parsed.items():
            for key, val in fields.items():
                if val == "не указано":
                    empty_counter[f"{group}.{key}"] += 1

        status = "✓" if not problems else f"⚠️ {len(problems)} проблем"
        print(f"  {status} {md_file.name} → {out_file.name}")

    print()
    if all_problems:
        print(f"⚠️ Файлов с проблемами: {len(all_problems)}")
        for fname, probs in list(all_problems.items())[:5]:
            print(f"\n  {fname}:")
            for p in probs[:5]:
                print(f"    - {p}")
    else:
        print("✅ Все файлы прошли валидацию контракта")

    print("\n📊 ТОП-20 полей с «не указано»:")
    for field, count in empty_counter.most_common(20):
        print(f"  {field}: {count}/100")

    print(f"\n📁 JSON лежат в {RESULT_DIR}/")


if __name__ == "__main__":
    main()