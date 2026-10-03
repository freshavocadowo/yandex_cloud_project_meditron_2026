"""Conservative rules tied to section, quotation and explicit case coding policy."""
from dataclasses import asdict, dataclass
import re
from typing import Callable

from .contract import BINARY, FIELDS, MISSING, validate_value
from .parser import Document

NUM = r"(\d+(?:[.,]\d+)?)"
SEP = r"\s*(?:[:=|]\s*)?"
DATE = r"(\d{2}\.\d{2}\.\d{4})"


@dataclass
class Fact:
    field: str
    value: str
    quote: str
    start: int
    end: int
    section: str
    context: str
    source: str = "rules"

    def export(self):
        return asdict(self)


def clause(text: str, start: int, end: int) -> str:
    left = [m for m in re.finditer(r";|\n|\.(?=\s+[А-ЯЁA-Z])", text) if m.end() <= start]
    a = left[-1].end() if left else 0
    right = next((m for m in re.finditer(r";|\n|\.(?=\s+[А-ЯЁA-Z])", text) if m.start() >= end - 1), None)
    b = max(end, right.start()) if right else len(text)
    return text[a:b]


def negated(text: str, start: int, end: int) -> bool:
    chunk = clause(text, start, end).lower()
    return bool(re.search(r"\bне\s+(?:кур|пров|выполн|выяв|зарегистр|отмеч|определ)|\bбез\b|отрица|нет\b|не получено|не было|отмен[её]н|исключ[её]н", chunk))


def extract(doc: Document) -> tuple[dict[str, Fact], list[str]]:
    facts: dict[str, Fact] = {}
    warnings = []

    def matches(pattern: str, kinds: set[str]):
        for sec in doc.sections:
            if sec.kind not in kinds:
                continue
            for m in re.finditer(pattern, doc.text[sec.start:sec.end], re.I):
                yield m, sec, sec.start + m.start(), sec.start + m.end()

    def add(field: str, value: str, start: int, end: int, kind: str, context="primary"):
        if not validate_value(field, value):
            warnings.append(f"invalid_rule_value:{field}")
            return
        if field not in facts:
            facts[field] = Fact(field, value, doc.text[start:end], start, end, kind, context)

    def find(field: str, pattern: str, kinds: set[str], transform: Callable = lambda m: m.group(1).replace(",", "."), reject_negative=False):
        for m, sec, a, b in matches(pattern, kinds):
            if reject_negative and negated(doc.text, a, b):
                continue
            add(field, transform(m), a, b, sec.kind)

    header = {"header"}
    diag = {"diagnosis"}
    exam = {"exam"}
    labs = {"labs"}
    ecg = {"ecg"}
    echo = {"echo"}
    find("admission_date", rf"(?:поступил[а-я]*|дата госпитализации|дата поступления){SEP}{DATE}", header)
    find("discharge_date", rf"(?:выписан[а-я]*|дата выписки){SEP}{DATE}", header)
    find("admission_date", rf"период лечения\s*:\s*с\s*{DATE}\s*по\s*{DATE}", header, lambda m: m.group(1))
    find("discharge_date", rf"период лечения\s*:\s*с\s*{DATE}\s*по\s*{DATE}", header, lambda m: m.group(2))
    find("diagnosis_icd", r"(?:МКБ(?:-10)?|код диагноза)\s*[: ]*(I\d{2}(?:\.\d+)?)", diag, lambda m: m.group(1).upper())
    for field, pattern in {
        "art_hyper": r"гипертоническ[а-яё]* болезн[а-яё]*|артериальн[а-яё]* гипертензи[а-яё]*|\bГБ\b",
        "dm": r"сахарн[а-яё]* диабет[а-яё]*|\bСД\s*[12]",
        "copd": r"\bХОБЛ\b|хроническ[а-яё]* обструктивн[а-яё]* болезн[а-яё]* л[её]гких",
        "atr_fibril": r"фибрилляци[а-яё]* предсердий|трепетани[а-яё]* предсердий|\bФП\b",
    }.items():
        for m, sec, a, b in matches(pattern, diag):
            negative = negated(doc.text, a, b)
            # Include the denial in the evidence, rather than a disease noun alone.
            q = clause(doc.text, a, b)
            qa = doc.text.rfind(q, 0, b + len(q))
            if qa < 0:
                qa = a
                q = doc.text[a:b]
            add(field, "0" if negative else "1", qa, qa+len(q), sec.kind, "negation" if negative else "diagnosis")
    find("ckd", r"(ХБП(?:\s*[1-5][АБAB]?)?|хроническая болезнь почек(?:\s*[1-5][АБAB]?)?)", diag, lambda m: m.group(1), True)
    find("hf", r"(ХСН(?:\s*[1-4IАБAB]+)?(?:,?\s*ФК\s*[1-4IV]+)?)", diag, lambda m: m.group(1), True)
    roman = {"I": "1", "II": "2", "III": "3", "IV": "4"}
    find("killip", r"Killip\s*[:=-]?\s*(IV|III|II|I|[1-4])\b", diag | exam, lambda m: roman.get(m.group(1).upper(), m.group(1)))
    find("mi_localisation", r"(?:инфаркт[^.;\n]{0,50})(передн[а-яё]*|нижн[а-яё]*|боков[а-яё]*)", diag, lambda m: "A" if m.group(1).lower().startswith("перед") else "I" if m.group(1).lower().startswith("ниж") else "L")
    for m, sec, a, b in matches(r"(?:без\s+(?:подъ[её]ма|элевации)|с\s+(?:подъ[её]мом|элевацией))\s*(?:сегмента\s*)?ST|\bNSTEMI\b|\bSTEMI\b", diag):
        add("type_acs", "NSTEMI" if re.search(r"без|NSTEMI", m.group(), re.I) else "STEMI", a, b, sec.kind, "diagnosis")
    for m, sec, a, b in matches(r"(?:провед[её]н[а-яё]*\s+(?:системный\s+)?тромболизис|тромболизис\s+(?:провед[её]н|выполнен)|ТЛТ\s+(?:проведена|выполнена))", {"treatment", "diagnosis"}):
        add("tlt", "0" if negated(doc.text, a, b) else "1", a, b, sec.kind, "treatment")

    for f, label in {"bmi": "ИМТ|индекс массы тела", "height": "рост", "weight": "масса тела|вес", "rr": "ЧДД|частота дыхания", "spo2": "SpO2|сатурация", "bpm": "пульс|ЧСС"}.items():
        find(f, rf"(?:{label}){SEP}{NUM}", exam)
    find("bp", rf"(?:АД|артериальное давление){SEP}(\d{{2,3}}\s*/\s*\d{{2,3}})", exam, lambda m: re.sub(r"\s", "", m.group(1)))
    find("smoking", r"(не курит|бросил[а]? курить|курит)", {"history", "exam"}, lambda m: m.group(1)[0].upper()+m.group(1)[1:].lower())
    find("ecg_bpm", rf"ЧСС{SEP}{NUM}", ecg)
    find("ecg_rythm", r"(синусов[а-яё]+)\s+ритм|ритм\s+(синусов[а-яё]+)|(фибрилляция предсердий|трепетание предсердий)", ecg, lambda m: "синусовый" if m.group(1) or m.group(2) else m.group(3).lower())
    for f, pat in {"ecg_avb": r"(?:АВ|AV)[- ]?блокад[а-яё]*(?:\s*[IV1-3]+\s*(?:степени|ст\.))?", "ecg_elevation": r"(?:подъ[её]м[а-яё]*|элеваци[а-яё]*)\s*(?:сегмента\s*)?ST[^.;\n]*"}.items():
        for m, sec, a, b in matches(pat, ecg):
            q = clause(doc.text, a, b)
            qa = doc.text.find(q, sec.start)
            add(f, "0" if negated(doc.text, a, b) else "1", qa, qa+len(q), sec.kind, "ecg")
    for f, label in {"echo_ef": "ФВ(?: ЛЖ)?|фракция выброса", "echo_lvd": "КДР ЛЖ", "echo_lvd_2": "ЛП"}.items():
        find(f, rf"(?:{label}){SEP}{NUM}", echo)
    find("echo_mr", r"(митральная регургитация\s*[0-4IV]+\s*(?:ст\.|степени)?)", echo, lambda m: m.group(1), True)
    find("echo_zone", r"((?:гипокинез|акинез)[^.;\n]+)", echo, lambda m: m.group(1).strip(), True)
    find("rg_date", rf"(?:рентгенограмма ОГК|рентгенография(?: грудной клетки)?|ОГК)\s*(?:от\s*)?{DATE}", {"xray"})
    find("rg_pc", r"((?:признаки\s+)?(?:венозного застоя|от[её]ка л[её]гких)[^.;\n]*)", {"xray"}, lambda m: m.group(1).strip(), True)

    ca = {"ca"}
    find("ca_date", rf"(?:коронарография|КАГ)\s*(?:от\s*)?{DATE}|{DATE}\s*[.:]\s*(?:коронарография|КАГ)", ca, lambda m: m.group(1) or m.group(2))
    find("ca_date", rf"{DATE}\s*(?:выполнена|проведена)\s*(?:селективная\s*)?(?:КАГ|коронарография)", ca)
    for m, sec, a, b in matches(r"(?:отказ[^.\n]*коронарографии|отказ[^.\n]*КАГ|(?:коронарографи[а-я]*|КАГ)[^.\n]*отказ)", ca | {"treatment"}):
        add("ca_fact", "R", a, b, sec.kind, "refusal")
    if "ca_date" in facts:
        f = facts["ca_date"]
        facts["ca_fact"] = Fact("ca_fact", "Y", f.quote, f.start, f.end, f.section, "procedure")
    else:
        find("ca_fact", r"((?:выполнена|проведена)\s+(?:селективная\s*)?(?:коронарография|КАГ))", ca, lambda m: "Y", True)
    if facts.get("ca_fact") and facts["ca_fact"].value == "Y":
        for f, name in {"ca_lad": "ПМЖВ|LAD|передняя межжелудочковая артерия", "rca": "ПКА|RCA|правая коронарная артерия"}.items():
            for m, sec, a, b in matches(rf"(?:{name})\s*[:=-]?\s*(?:стеноз\s*(?:до\s*)?)?(\d{{1,3}}\s*%|окклюзия|без стеноза|без сужения)", ca):
                raw = m.group(1)
                n = int(re.search(r"\d+", raw).group()) if re.search(r"\d", raw) else 100 if "окклюз" in raw.lower() else 0
                if n <= 100:
                    add(f, "2" if n >= 90 else "1" if n >= 50 else "0", a, b, sec.kind, "procedure")
            if f not in facts and next(matches(rf"(?:{name})\s*:\s*гемодинамически значимого стеноза нет", ca), None):
                warnings.append(f"qualitative_stenosis_needs_review:{f}")
    else:
        facts.pop("ca_date", None)

    for f, label in {"crea": "креатинин", "glu": "глюкоза", "hb": "гемоглобин", "ldl": "ХС[-–]ЛПНП|холестерин ЛПНП|ЛПНП", "leucocytes": "лейкоциты", "thrombocytes": "тромбоциты", "tot_chol": "общий холестерин"}.items():
        # Only primary lab sections; discard control lines and historical measurements.
        pat = rf"(?:{label}){SEP}{NUM}"
        for m, sec, a, b in matches(pat, labs):
            line_start = max(sec.start, doc.text.rfind("\n", sec.start, a) + 1)
            prefix = doc.text[line_start:a]
            if re.search(r"контрол|повтор|перед выпиской|ранее|анамнез", prefix, re.I):
                continue
            add(f, m.group(1).replace(",", "."), a, b, sec.kind)
    find("card_trop", r"тропонин(?:овый|ов[а-яё]*)?\s*(?:тест\s*)?[—:=-]?\s*(положительный|отрицательный|\d+(?:[.,]\d+)?)", labs)

    drug_patterns = {
        "aspirin": r"ацетилсалициловая кислота|аспирин|АСК",
        "2_aag": r"клопидогрел|тикагрелор|прасугрел",
        "bb": r"метопролол|бисопролол|карведилол|небиволол|атенолол",
        "ace_ing_sartan": r"[а-яё]*(?:прил|сартан)|лозартан",
        "statin": r"аторвастатин|розувастатин|симвастатин|питавастатин|правастатин",
        "anticoagulant": r"апиксабан|ривароксабан|дабигатран|варфарин|эноксапарин|гепарин",
    }
    for f, names in drug_patterns.items():
        for m, sec, a, b in matches(rf"\b((?:{names})\b[^\n;|]*)", {"therapy"}):
            if negated(doc.text, a, b):
                continue
            raw = m.group(1).strip().rstrip(".")
            add(f, raw, a, a+len(raw), sec.kind, "discharge_prescription")
    return facts, sorted(set(warnings))


def defaults() -> dict[str, str]:
    return {f: "0" if f in BINARY else "N" if f in {"ca_fact", "mi_localisation"} else "NA" if f == "type_acs" else MISSING for f in FIELDS}
