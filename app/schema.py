"""Контракт результата: 9 групп / 50 ключей, все значения — строки.

Порядок групп и ключей повторяет participant-output-template-50.json.
"""
import re

NOT_FOUND = "не указано"

GROUPS: dict[str, tuple[str, ...]] = {
    "даты эпизода": ("admission_date", "discharge_date"),
    "диагноз": ("art_hyper", "atr_fibril", "ckd", "copd", "diagnosis_icd", "dm", "hf", "killip",
                "mi_localisation", "tlt", "type_acs"),
    "осмотр при поступлении": ("bmi", "bp", "bpm", "height", "rr", "smoking", "spo2", "weight"),
    "ЭКГ": ("ecg_avb", "ecg_bpm", "ecg_elevation", "ecg_rythm"),
    "ЭХО-КГ": ("echo_ef", "echo_lvd", "echo_lvd_2", "echo_mr", "echo_zone"),
    "рентген грудной полости": ("rg_date", "rg_pc"),
    "коронарография": ("ca_date", "ca_fact", "ca_lad", "rca"),
    "Лабораторные данные": ("card_trop", "crea", "glu", "hb", "ldl", "leucocytes", "thrombocytes", "tot_chol"),
    "медикаментозная терапия": ("2_aag", "ace_ing_sartan", "anticoagulant", "aspirin", "bb", "statin"),
}
GROUP_OF = {key: group for group, keys in GROUPS.items() for key in keys}
FIELDS = tuple(GROUP_OF)

# Описания из ТЗ: подписи в веб-интерфейсе и подсказки для LLM.
DESCRIPTIONS = {
    "admission_date": "Дата поступления на эту госпитализацию",
    "discharge_date": "Дата выписки без времени",
    "art_hyper": "Гипертоническая болезнь как диагноз, не просто высокое давление: 1/0",
    "atr_fibril": "Фибрилляция или трепетание предсердий: 1/0",
    "ckd": "Хроническая болезнь почек и её стадия, например «ХБП 3А»",
    "copd": "Хроническая обструктивная болезнь лёгких: 1/0",
    "diagnosis_icd": "Код основного диагноза по МКБ-10, например I21.1",
    "dm": "Сахарный диабет как диагноз, не только повышенная глюкоза: 1/0",
    "hf": "Хроническая сердечная недостаточность со стадией или классом, например «ХСН 2А, ФК 2»",
    "killip": "Прямо указанный класс Killip арабской цифрой, без вычисления",
    "mi_localisation": "Область инфаркта: A передняя, I нижняя, L боковая, N не уточнена",
    "tlt": "Выполненный лекарственный тромболизис, не стентирование: 1/0",
    "type_acs": "Тип ОКС: STEMI с подъёмом ST, NSTEMI без него, NA тип не установлен",
    "bmi": "Прямо указанный индекс массы тела, не вычисленный заново",
    "bp": "Давление при первичном осмотре, верхнее/нижнее",
    "bpm": "Пульс или ЧСС при первичном осмотре",
    "height": "Рост, см",
    "rr": "Частота дыхания в минуту, ЧДД",
    "smoking": "Указанный статус курения, например «Не курит»",
    "spo2": "Насыщение крови кислородом, сатурация, %",
    "weight": "Масса тела, кг",
    "ecg_avb": "Прямо указанная АВ-блокада: 1/0",
    "ecg_bpm": "ЧСС именно в записи ЭКГ",
    "ecg_elevation": "Прямо указанный подъём сегмента ST: 1/0",
    "ecg_rythm": "Названный в ЭКГ ритм сердца, например «синусовый»",
    "echo_ef": "Фракция выброса левого желудочка, %",
    "echo_lvd": "Размер левого желудочка рядом с «КДР ЛЖ», мм",
    "echo_lvd_2": "Размер левого предсердия рядом с «ЛП», мм",
    "echo_mr": "Степень митральной регургитации, например «Митральная регургитация 2 ст.»",
    "echo_zone": "Зона гипо-/акинеза, например «Гипокинез нижней стенки»",
    "rg_date": "Дата рентгенографии грудной клетки",
    "rg_pc": "Выявленный застой или отёк в лёгких (текст)",
    "ca_date": "Дата коронарографии (КАГ)",
    "ca_fact": "Коронарография: Y выполнена, R отказ, N нет сведений",
    "ca_lad": "ПМЖВ: 0 стеноз <50%, 1 — 50–89%, 2 — ≥90% или окклюзия",
    "rca": "ПКА: 0 стеноз <50%, 1 — 50–89%, 2 — ≥90% или окклюзия",
    "card_trop": "Первый результат тропонина, например «положительный»",
    "crea": "Первое значение креатинина, мкмоль/л",
    "glu": "Первое значение глюкозы крови, ммоль/л",
    "hb": "Первое значение гемоглобина, г/л",
    "ldl": "Холестерин ЛПНП, не общий холестерин",
    "leucocytes": "Первое значение лейкоцитов",
    "thrombocytes": "Первое значение тромбоцитов",
    "tot_chol": "Общий холестерин",
    "2_aag": "Второй антиагрегант кроме аспирина (клопидогрел, тикагрелор, прасугрел) с дозировкой",
    "ace_ing_sartan": "Препарат на «-прил» или «-сартан» с дозировкой",
    "anticoagulant": "Антикоагулянт (апиксабан, ривароксабан, дабигатран, варфарин) с дозировкой",
    "aspirin": "Аспирин / ацетилсалициловая кислота / АСК с дозировкой",
    "bb": "Бета-блокатор (бисопролол, метопролол …) с дозировкой",
    "statin": "Статин (аторвастатин, розувастатин …) с дозировкой",
}

# Бинарные коды: 1 — прямое указание, 0 — явное отрицание или отсутствие упоминания (кодовое правило).
BINARY = ("art_hyper", "atr_fibril", "copd", "dm", "tlt", "ecg_avb", "ecg_elevation")
ENUMS: dict[str, set[str]] = {
    **{key: {"0", "1"} for key in BINARY},
    "killip": {"1", "2", "3", "4"},
    "mi_localisation": {"A", "I", "L", "N"},
    "type_acs": {"STEMI", "NSTEMI", "NA"},
    "ca_fact": {"Y", "R", "N"},
    "ca_lad": {"0", "1", "2"},
    "rca": {"0", "1", "2"},
}
# Значение, если признак в тексте не найден.
DEFAULTS = {**{key: "0" for key in BINARY}, "ca_fact": "N"}

DATE_FIELDS = ("admission_date", "discharge_date", "rg_date", "ca_date")
NUMBER_FIELDS = ("bmi", "bpm", "height", "rr", "spo2", "weight", "ecg_bpm", "echo_ef", "echo_lvd", "echo_lvd_2",
                 "crea", "glu", "hb", "ldl", "leucocytes", "thrombocytes", "tot_chol")
FORMATS: dict[str, re.Pattern] = {
    **{key: re.compile(r"\d{2}\.\d{2}\.\d{4}") for key in DATE_FIELDS},
    **{key: re.compile(r"\d+(?:\.\d+)?") for key in NUMBER_FIELDS},
    "bp": re.compile(r"\d{2,3}/\d{2,3}"),
    "diagnosis_icd": re.compile(r"[A-Z]\d{2}(?:\.\d{1,2})?"),
    "ckd": re.compile(r"ХБП(?: С?\d[АБ]?)?"),
}


def default(key: str) -> str:
    return DEFAULTS.get(key, NOT_FOUND)


def empty() -> dict[str, dict[str, str]]:
    return {group: {key: default(key) for key in keys} for group, keys in GROUPS.items()}


def nest(flat: dict[str, str]) -> dict[str, dict[str, str]]:
    """{key: value} -> {группа: {key: value}} в порядке шаблона; пропущенные ключи — значение по умолчанию."""
    return {group: {key: flat.get(key, default(key)) for key in keys} for group, keys in GROUPS.items()}


def flatten(result: dict) -> dict[str, str]:
    return {key: value for group in result.values() if isinstance(group, dict) for key, value in group.items()}


def check_value(key: str, value) -> str | None:
    """Код ошибки для одного значения или None."""
    if not isinstance(value, str):
        return "not_string"
    if value == NOT_FOUND:
        return "not_found_for_binary" if key in BINARY or key == "ca_fact" else None
    if key in ENUMS and value not in ENUMS[key]:
        return "not_in_enum"
    if key in FORMATS and not FORMATS[key].fullmatch(value):
        return "bad_format"
    return None


def validate(result) -> list[str]:
    """Список ошибок контракта; пустой — JSON валиден."""
    if not isinstance(result, dict):
        return ["root_not_object"]
    errors = [f"missing_group:{g}" for g in GROUPS if g not in result]
    errors += [f"extra_group:{g}" for g in result if g not in GROUPS]
    for group, keys in GROUPS.items():
        values = result.get(group)
        if not isinstance(values, dict):
            if group in result:
                errors.append(f"group_not_object:{group}")
            continue
        errors += [f"missing_key:{k}" for k in keys if k not in values]
        errors += [f"extra_key:{k}" for k in values if k not in keys]
        for key in keys:
            if key in values and (code := check_value(key, values[key])):
                errors.append(f"{code}:{key}")
    return errors
