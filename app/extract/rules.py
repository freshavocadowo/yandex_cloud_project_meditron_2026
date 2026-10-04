"""Извлечение 50 признаков правилами: regex + словари по разделам обезличенного текста.

Каждое значение сопровождается цитатой-подтверждением: start/end — смещения в
обезличенном тексте, evidence == text[start:end]. Значение без цитаты — только
значение по умолчанию (source="default"): «не указано» или 0 по кодовому правилу.
"""
from dataclasses import dataclass
import re
from typing import Iterator

from ..normalize import DATE_RE, arabic, date, number, phrase, stenosis_grade
from ..schema import FIELDS, NOT_FOUND, default
from ..segment import Segmented


@dataclass
class Finding:
    value: str
    evidence: str = ""
    start: int = -1
    end: int = -1
    source: str = "rule"  # rule | llm | default


def rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


DATE = rf"(?:{DATE_RE})"
NUM = r"(\d+(?:[.,]\d+)?)"
SEP = r"\s*[:=—–-]?\s*"
# Разделы с повторными измерениями и рекомендациями: в них не ищем признаки госпитализации.
NOISY = frozenset({"followup", "therapy", "notes", "treatment", "consult"})
NEG = rx(r"(?<![\w-])(?:нет|не|без|отрица\w*|отсутств\w*|исключ\w*)(?![\w-])")
# Границы предложения: «;», перевод строки, точка не внутри числа («5.4») и не в «рт. ст.».
SENTENCE_END = re.compile(r"[;\n]|(?<!\d)\.(?!\d)(?!\s*ст\.)|\.(?=\s)(?!\s*ст\.)")
CLAUSE_END = re.compile(rf"{SENTENCE_END.pattern}|,")


class Doc:
    def __init__(self, seg: Segmented):
        self.seg = seg
        self.text = seg.text

    def ranges(self, kinds=None, exclude=NOISY) -> list[tuple[int, int]]:
        """kinds=None — все разделы, кроме exclude."""
        return [(s.body_start, s.end) for s in self.seg.sections
                if (s.kind in kinds if kinds is not None else s.kind not in exclude)]

    def has(self, kind: str) -> bool:
        return any(s.kind == kind for s in self.seg.sections)

    def finditer(self, pattern: re.Pattern, ranges) -> Iterator[re.Match]:
        for lo, hi in ranges:
            yield from pattern.finditer(self.text, lo, hi)

    def first(self, pattern: re.Pattern, *scopes) -> re.Match | None:
        """Первое совпадение в первой области, где оно есть; область — список диапазонов."""
        for ranges in scopes:
            m = next(self.finditer(pattern, ranges), None)
            if m:
                return m
        return None

    def bounds(self, start: int, end: int, sep=SENTENCE_END) -> tuple[int, int]:
        """Предложение (или клауза), содержащее [start, end), в пределах раздела."""
        section = self.seg.section_at(start)
        left = section.body_start if section.body_start <= start else section.start
        for m in sep.finditer(self.text, max(left, start - 400), start):
            left = m.end()
        m = sep.search(self.text, end, section.end)
        return left, m.start() if m else section.end

    def sentences(self, ranges) -> Iterator[tuple[int, int]]:
        for lo, hi in ranges:
            pos = lo
            for m in SENTENCE_END.finditer(self.text, lo, hi):
                if self.text[pos:m.start()].strip():
                    yield pos, m.start()
                pos = m.end()
            if self.text[pos:hi].strip():
                yield pos, hi

    def found(self, value: str, start: int, end: int) -> Finding:
        raw = self.text[start:end]
        start += len(raw) - len(raw.lstrip())
        end -= len(raw) - len(raw.rstrip())
        return Finding(value, self.text[start:end], start, end)

    def negated(self, start: int, end: int) -> bool:
        # Совпадение может захватить точку-границу («2 ст.»): иначе клауза продлится в следующее предложение.
        while end > start + 1 and self.text[end - 1] in ".;,":
            end -= 1
        lo, hi = self.bounds(start, end, CLAUSE_END)
        return bool(NEG.search(self.text, lo, hi))


# ---------- даты эпизода ----------
ADMISSION = rx(rf"(?:поступил[аи]?|поступлени[ея]|дата\s+поступления|госпитализирован[аы]?|дата\s+госпитализации"
               rf"|госпитализаци[ия])(?:\s+в\s+стационар)?{SEP}(?:от\s+)?({DATE})")
DISCHARGE = rx(rf"(?:выписан[аы]?|дата\s+выписки|выписки)(?:\s+из\s+стационара)?{SEP}(?:от\s+)?({DATE})")
PERIOD = rx(rf"(?:период\s+(?:лечения|госпитализации)|находил\w*\s+на\s+(?:стационарном\s+)?лечении)"
            rf"{SEP}с\s+({DATE})\s*(?:г\.?\s*)?(?:по|до|[-–—])\s*({DATE})")

# ---------- диагноз ----------
ICD = rx(r"МКБ[\s-]*(?:10)?\s*[:—-]?\s*(?:код\s*)?([A-ZА-ЯІ]\d{2}(?:\.\d{1,2})?)")
ICD_BARE = re.compile(r"(?<![\w.])([IІ]2[0-5](?:\.\d)?)(?![\w])")
LOOKALIKE = str.maketrans("АВСЕКМНОРТХІ", "ABCEKMHOPTXI")
COMORBID = {
    "art_hyper": rx(r"гипертоническ\w*\s+болезн\w*|(?-i:\bГБ\b)|(?:артериальн|эссенциальн)\w*\s+гипертензи\w*"),
    "atr_fibril": rx(r"фибрилляци\w*\s+предсерди\w*|трепетани\w*\s+предсерди\w*|(?-i:\bФП\b)|мерцательн\w*\s+аритми\w*"),
    "copd": rx(r"\bХОБЛ\b|хроническ\w*\s+обструктивн\w*\s+болезн\w*\s+л[её]гких"),
    "dm": rx(r"сахарн\w*\s+диабет\w*|(?-i:\bСД\b)"),
}
HF = rx(r"\bХСН\b|хроническ\w*\s+сердечн\w*\s+недостаточност\w*")
HF_STAGE = rx(r"\s*(?:стади[ия]\s*)?(III|II|I|[0-3])\s*([АБAB])?(?![\w])")
HF_GAP = rx(r"[\s,;]*(?:ст\.?|стади\w*)?[\s,;]*")
HF_CLASS = rx(r"(?:ФК|NYHA)\s*(?:класс\s*)?(IV|III|II|I|[1-4])(?![\w])")
CKD = rx(r"\bХБП\b|хроническ\w*\s+болезн\w*\s+почек")
CKD_STAGE = rx(r"\s*(?:[СC]\s*)?(?:стади[ия]\s*)?([1-5])\s*([АБAB])?(?![\d])")
KILLIP = rx(r"(?:Killip|Киллип\w*)\s*[:—-]?\s*(?:класс\w*\s*)?(IV|III|II|I|[1-4])(?![\w])")
MI = rx(r"инфаркт\w*\s+миокард\w*|(?-i:\bО?ИМ\b|\bN?STEMI\b|\bО?ИМб?п(?:ST|СТ)\b)")
UNSTABLE = rx(r"нестабильн\w*\s+стенокарди\w*|прогрессирующ\w*\s+стенокарди\w*")
NSTEMI = rx(r"без\s+(?:подъ[её]м\w*|элевац\w*)\s+(?:сегмента\s+)?(?:ST|СТ)|\bNSTEMI\b|\bО?(?:ИМ|ОКС)бп(?:ST|СТ)\b")
STEMI = rx(r"(?:\bс|\bсо)\s+(?:подъ[её]м\w*|элевац\w*)\s+(?:сегмента\s+)?(?:ST|СТ)|(?<!N)\bSTEMI\b|\bО?(?:ИМ|ОКС)п(?:ST|СТ)\b")
LOCALISATION = [
    (rx(r"передн\w*|переднеперегородоч\w*|перегородоч\w*|верхушечн\w*"), "A"),
    (rx(r"нижн\w*|задн\w*|диафрагмальн\w*"), "I"),
    (rx(r"боков\w*|латеральн\w*"), "L"),
]
ICD_LOCALISATION = {"I21.0": "A", "I21.1": "I", "I21.2": "L"}
TLT = rx(r"тромболизис\w*|тромболизи\w*|\bТЛТ\b|тромболитическ\w*|(?:альтеплаз|тенектеплаз|фортелизин|проурокиназ"
         r"|стрептокиназ|пуролаз|метализ|актилиз)\w*")

# ---------- осмотр ----------
EXAM = {
    "bp": rx(r"(?:\bАД\b|артериальн\w*\s+давлени\w*)[^\d\n;.]{0,15}?(\d{2,3})\s*/\s*(\d{2,3})"),
    "bpm": rx(r"(?:пульс(?!ац)\w*|\bЧСС\b|частота\s+сердечных\s+сокращений)[^\d\n;.]{0,20}?(\d{2,3})(?!\d|[.,/]\d)"),
    "rr": rx(r"(?:\bЧДД\b|(?-i:\bЧД\b)|частота\s+дыхани\w*(?:\s+движений)?)[^\d\n;.]{0,10}?(\d{1,2})(?!\d|[.,]\d)"),
    "spo2": rx(r"(?:SpO2|SpO₂|SaO2|сатураци\w*(?:\s+кислорода)?|насыщени\w*\s+крови\s+кислородом)[^\d\n;.]{0,10}?"
               r"(\d{2,3})\s*%?"),
    "height": rx(r"\bрост\w*[^\d\n;.]{0,5}?(\d{3}(?:[.,]\d)?)\s*см"),
    "weight": rx(r"(?:масса\s+тела|\bвес\b)[^\d\n;.]{0,5}?(\d{2,3}(?:[.,]\d)?)\s*кг"),
    "bmi": rx(r"(?:\bИМТ\b|индекс\s+массы\s+тела)[^\d\n;.]{0,5}?(\d{2}(?:[.,]\d{1,2})?)(?![\d])"),
}
SMOKING = rx(r"никогда\s+не\s+курил\w*|не\s+курит|курени\w*\s+отрицает|(?:бросил\w*|прекратил\w*)\s+курить"
             r"|отказал\w*\s+от\s+курения|курил\w*\s+(?:ранее|в\s+прошлом)|бывш\w*\s+курильщик\w*|курит(?:\s+до\s+[^.;\n]+)?"
             r"|курильщик\w*|(?:стаж|индекс)\s+курени\w*[^.;\n]*|курени\w*\s*[:—-]\s*[^.;\n]+")

# ---------- ЭКГ ----------
ECG_WORD = rx(r"\bЭКГ\b|электрокардиограм\w*")
ECG_CONTENT = rx(r"ритм|\bЧСС\b|\bST\b")
ECG_CONTROL = rx(r"контрол|повторн|динамик|на\s+фоне\s+лечения|при\s+выписке")
RHYTHM = [
    (rx(r"синусов\w*"), "синусовый"),
    (rx(r"фибрилляци\w*\s+предсерди\w*|мерцательн\w*\s+аритми\w*"), "фибрилляция предсердий"),
    (rx(r"трепетани\w*\s+предсерди\w*"), "трепетание предсердий"),
]
RHYTHM_OTHER = rx(r"ритм\w*\s*[:—-]?\s*([а-яё]+(?:ый|ий|ой))|([а-яё]+(?:ый|ий|ой))\s+ритм")
ECG_BPM = rx(r"(?:\bЧСС\b|частота\s+сердечных\s+сокращений)[^\d\n;.]{0,10}?(\d{2,3})(?![\d])")
ELEVATION = rx(r"(?:элевац\w*|подъ[её]м\w*)\s+(?:сегмента\s+)?(?:ST|СТ)\b|\bST\s*[-–]?\s*(?:элевац|подъ[её]м)\w*")
AVB = rx(r"(?:\bАВ|\bAV|\bА-В|атриовентрикулярн\w*)[\s-]*блокад\w*")

# ---------- ЭхоКГ ----------
ECHO = {
    "echo_ef": rx(r"(?:\bФВ\b|фракци\w*\s+выброса)(?:\s*ЛЖ)?[^\d\n;]{0,15}?(\d{1,2}(?:[.,]\d)?)\s*%"),
    "echo_lvd": rx(r"(?:\bКДР\b|конечн\w*\s+диастолическ\w*\s+размер\w*)(?:\s*ЛЖ)?[^\d\n;]{0,8}?(\d{2,3}(?:[.,]\d)?)"),
    "echo_lvd_2": rx(r"(?:(?-i:\bЛП\b)|лев\w*\s+предсерди\w*)[^\d\n;]{0,8}?(\d{2,3}(?:[.,]\d)?)(?![\d])"),
}
MR_DEGREE = r"(?:\d(?:[-–,.]\d)?|IV|III|II|I)\s*(?:ст\.?|степени)"
MR_ADJ = r"(?:незначительн|умеренн|выраженн|минимальн|л[её]гк|тяжел|гемодинамически\s+незначим)\w*"
MR = rx(rf"(?:{MR_ADJ}\s+)?митральн\w*\s+регургитаци\w*(?:\s*[:—-]?\s*(?:{MR_DEGREE}|{MR_ADJ}))?"
        rf"|регургитаци\w*\s+на\s+(?:митральн\w*\s+клапан\w*|\bМК\b)(?:\s*[:—-]?\s*{MR_DEGREE})?|(?-i:\bМР)\s*{MR_DEGREE}")
ZONE = rx(r"(?:гипокинез|акинез|дискинез)\w*[^.;\n]*")
ZONE_TAIL = rx(r"\s+(?:ЛЖ|левого\s+желудочка)\s*$")

# ---------- рентген ----------
XRAY_WORD = rx(r"рентген\w*|\bR-?графи\w*|\bRg\b")
CONGESTION = rx(r"застой\w*|застоя|от[её]к\w*\s+л[её]гких|интерстициальн\w*\s+от[её]к\w*|альвеолярн\w*\s+от[её]к\w*"
                r"|гиперволеми\w*|венозн\w*\s+полнокрови\w*|кардиогенн\w*\s+от[её]к\w*")
CONCLUSION = rx(r"заключение\s*[:—-]\s*")

# ---------- коронарография ----------
CA_WORD = rx(r"коронарограф\w*|коронароангиограф\w*|(?-i:\bКАГ\b|\bКГ\b)|ангиографи\w*\s+коронарн\w*")
CA_REFUSED = rx(r"отказ\w*")
CA_NOT_DONE = rx(r"не\s+(?:выполнял|проводил|выполнен|проведен|проведён)\w*")
ARTERY_DESC = rx(r"(?-i:\bПМЖВ\b|\bПКА\b|\bОА\b)|ствол\s+ЛКА|стеноз\w*|окклюз\w*")
ARTERIES = {
    "ca_lad": rx(r"\bПМЖВ\b|\bПМЖА\b|\bПНА\b|\bLAD\b|передн\w*\s+межжелудочков\w*\s+(?:ветв|артери)\w*"),
    "rca": rx(r"\bПКА\b|\bRCA\b|прав\w*\s+коронарн\w*\s+артери\w*"),
}
OCCLUSION = rx(r"окклюз\w*|окклюдирован\w*|закрыт\w*|\bкульт\w*|тотальн\w*")
PERCENT = re.compile(r"(\d{1,3})\s*%")
NO_STENOSIS = rx(r"без\s+(?:гемодинамически\s+)?значим\w*|значим\w*\s+стеноз\w*\s+нет|стеноз\w*\s+нет|без\s+стеноз\w*"
                 r"|не\s+изменен\w*|интактн\w*|без\s+поражени\w*|неровност\w*\s+контур\w*|без\s+патологи\w*")

# ---------- лаборатория ----------
LAB_VALUE = rf"(?:[^\d\n;]{{0,20}}?\(?\s*(?:от\s+)?{DATE}\s*\)?)?[^\d\n;]{{0,20}}?{NUM}(?![\d]|[./]\d{{1,2}}[./]\d)"
LABS = {key: rx(f"(?:{label}){LAB_VALUE}") for key, label in {
    "crea": r"(?<!клиренс\s)креатинин\w*",
    "glu": r"глюкоз\w*|гликеми\w*",
    "hb": r"(?<!гликированный\s)гемоглобин\w*|\bHb\b|\bHGB\b",
    "ldl": r"(?:\bХС[\s-]*)?\bЛПНП\b|холестерин\w*\s+(?:ЛПНП|липопротеи\w+\s+низкой\s+плотности)|\bLDL\b",
    "leucocytes": r"лейкоцит\w*|\bWBC\b",
    "thrombocytes": r"тромбоцит\w*|\bPLT\b",
    "tot_chol": r"\bОХС\b|общ\w*\s+холестерин\w*|холестерин\w*\s+общ\w*|холестерин(?![\w\s-]*(?:ЛП|липопрот))\w*",
}.items()}
TROPONIN = rx(r"тропонин\w*[^;\n]{0,40}?(?:(положительн\w*|отрицательн\w*|повышен\w*)"
              r"|(\d+(?:[.,]\d+)?)\s*(?:нг/мл|нг/л|пг/мл|мкг/л))")

# ---------- терапия ----------
DRUGS = {
    "aspirin": rx(r"ацетилсалицилов\w*(?:\s+кислот\w*)?|\bАСК\b|аспирин\w*|кардиомагнил\w*|тромбо\s*АСС\w*"),
    "2_aag": rx(r"клопидогрел\w*|тикагрелор\w*|прасугрел\w*|плавикс\w*|брилинт\w*|эффиент\w*"),
    "bb": rx(r"\b\w+лол\b|\b\w+лола\b|конкор\w*|беталок\w*|эгилок\w*"),
    "ace_ing_sartan": rx(r"\b\w+прил\w*|\b\w+[сз]артан\w*|престариум\w*"),
    "statin": rx(r"\b(?!нистатин)\w+статин\w*|крестор\w*|липримар\w*"),
    "anticoagulant": rx(r"апиксабан\w*|ривароксабан\w*|дабигатран\w*|эдоксабан\w*|варфарин\w*|эликвис\w*|ксарелто\w*"
                        r"|прадакс\w*|(?:эноксапарин|надропарин|далтепарин|фондапаринукс|гепарин)\w*"),
}
ANY_DRUG = re.compile("|".join(f"(?:{p.pattern})" for p in DRUGS.values()), re.IGNORECASE)
DRUG_CANCELLED = rx(r"не\s+назнач|отмен\w*|непереносим\w*|противопоказ\w*|аллерги\w*")
LIST_MARK = re.compile(r"^\s*(?:(?:\d+[.)]|[-•*–])\s*)?")


class Extractor:
    def __init__(self, seg: Segmented):
        self.doc = Doc(seg)
        self.text = seg.text
        self.out: dict[str, Finding] = {}

    # Области поиска: основной раздел, затем весь документ без «шумных» разделов.
    def scope(self, *kinds: str) -> list[list[tuple[int, int]]]:
        return [self.doc.ranges(kinds), self.doc.ranges()]

    def set(self, key: str, finding: Finding | None) -> None:
        if finding is not None:
            self.out[key] = finding

    def number(self, key: str, m: re.Match | None, group: int = 1) -> None:
        if m:
            f = self.doc.found(number(m.group(group)), m.start(), m.end())
            self.set(key, f)

    def run(self) -> dict[str, Finding]:
        for step in (self.dates, self.diagnosis, self.exam, self.ecg, self.echo, self.xray, self.ca, self.labs,
                     self.therapy):
            step()
        return {key: self.out.get(key) or Finding(default(key), source="default") for key in FIELDS}

    # ----- даты эпизода -----
    def dates(self) -> None:
        header, rest = self.doc.ranges(("header",)), self.doc.ranges(exclude=NOISY - {"consult"})
        m = self.doc.first(PERIOD, header, rest)
        if m and date(m.group(1)) and date(m.group(2)):
            self.set("admission_date", self.doc.found(date(m.group(1)), m.start(), m.end()))
            self.set("discharge_date", self.doc.found(date(m.group(2)), m.start(), m.end()))
        for key, pattern in (("admission_date", ADMISSION), ("discharge_date", DISCHARGE)):
            if key in self.out:
                continue
            for m in self.doc.finditer(pattern, header + rest):
                if value := date(m.group(1)):
                    self.set(key, self.doc.found(value, m.start(), m.end()))
                    break

    # ----- диагноз -----
    def diagnosis(self) -> None:
        diag = self.doc.ranges(("diagnosis",))
        history = self.doc.ranges(("history", "life_history", "header", "other"))
        icd = self.doc.first(ICD, diag, self.doc.ranges()) or self.doc.first(ICD_BARE, diag, self.doc.ranges())
        code = icd.group(1).upper().translate(LOOKALIKE) if icd else None
        if icd:
            self.set("diagnosis_icd", self.doc.found(code, icd.start(1), icd.end(1)))

        for key, pattern in COMORBID.items():
            self.set(key, self.binary(pattern, diag, history))
        if self.out.get("atr_fibril") is None:  # ФП, названная в ЭКГ, — тоже прямое указание
            self.set("atr_fibril", self.binary(COMORBID["atr_fibril"], self.ecg_record()))

        self.set("hf", self.staged(HF, diag + history, self.hf_value))
        self.set("ckd", self.staged(CKD, diag + history, self.ckd_value))

        m = self.doc.first(KILLIP, diag, self.doc.ranges())
        if m:
            self.set("killip", self.doc.found(arabic(m.group(1)), m.start(), m.end()))

        self.acs_type(diag, code, icd)
        m = next((m for m in self.doc.finditer(TLT, self.doc.ranges(exclude={"therapy", "notes"}))), None)
        if m:
            negative = self.doc.negated(m.start(), m.end())
            self.set("tlt", self.doc.found("0" if negative else "1", *self.doc.bounds(m.start(), m.end())))

    def binary(self, pattern: re.Pattern, *scopes) -> Finding | None:
        """1 — первое неотрицаемое упоминание; 0 с цитатой — только отрицания; None — не упомянуто."""
        negative = None
        for ranges in scopes:
            for m in self.doc.finditer(pattern, ranges):
                if not self.doc.negated(m.start(), m.end()):
                    return self.doc.found("1", m.start(), m.end())
                negative = negative or self.doc.found("0", *self.doc.bounds(m.start(), m.end(), CLAUSE_END))
        return negative

    def staged(self, pattern: re.Pattern, ranges, value_of) -> Finding | None:
        for m in self.doc.finditer(pattern, ranges):
            if self.doc.negated(m.start(), m.end()):
                continue
            value, end = value_of(m)
            return self.doc.found(value, m.start(), end)
        return None

    def hf_value(self, m: re.Match) -> tuple[str, int]:
        value, end = "ХСН", m.end()
        stage = HF_STAGE.match(self.text, end)
        if stage:
            value += f" {arabic(stage.group(1))}{(stage.group(2) or '').translate(str.maketrans('AB', 'АБ')).upper()}"
            end = stage.end()
        fc = HF_CLASS.match(self.text, HF_GAP.match(self.text, end).end())
        if fc:
            value += f", ФК {arabic(fc.group(1))}"
            end = fc.end()
        return value, end

    def ckd_value(self, m: re.Match) -> tuple[str, int]:
        stage = CKD_STAGE.match(self.text, m.end())
        if not stage:
            return "ХБП", m.end()
        letter = (stage.group(2) or "").translate(str.maketrans("ABab", "АБАБ")).upper()
        return f"ХБП {stage.group(1)}{letter}", stage.end()

    def acs_type(self, diag, code: str | None, icd: re.Match | None) -> None:
        scope = diag or self.doc.ranges()
        mi = next(self.doc.finditer(MI, scope), None)
        nstemi, stemi = next(self.doc.finditer(NSTEMI, scope), None), next(self.doc.finditer(STEMI, scope), None)
        unstable = next(self.doc.finditer(UNSTABLE, scope), None)
        if nstemi and mi:
            self.set("type_acs", self.doc.found("NSTEMI", nstemi.start(), nstemi.end()))
        elif stemi:
            self.set("type_acs", self.doc.found("STEMI", stemi.start(), stemi.end()))
        elif unstable or (nstemi and not mi):
            m = unstable or nstemi
            self.set("type_acs", self.doc.found("NA", m.start(), m.end()))
        elif code and icd:
            value = ("NSTEMI" if code.startswith("I21.4") else "STEMI" if code.startswith(("I21", "I22"))
                     else "NA" if code.startswith("I20") else None)
            if value:
                self.set("type_acs", self.doc.found(value, icd.start(1), icd.end(1)))

        if mi:
            lo, hi = self.doc.bounds(mi.start(), mi.end())
            hits = [(m.start(), m.end(), value) for pattern, value in LOCALISATION
                    for m in [pattern.search(self.text, lo, hi)] if m]
            if hits:
                start, end, value = min(hits)
                self.set("mi_localisation", self.doc.found(value, min(start, mi.start()), max(end, mi.end())))
            elif code in ICD_LOCALISATION and icd:
                self.set("mi_localisation", self.doc.found(ICD_LOCALISATION[code], icd.start(1), icd.end(1)))
            else:
                self.set("mi_localisation", self.doc.found("N", mi.start(), mi.end()))

    # ----- осмотр при поступлении -----
    def exam(self) -> None:
        scopes = self.scope("exam")
        for key, pattern in EXAM.items():
            m = self.doc.first(pattern, *scopes)
            if not m:
                continue
            if key == "bp":
                self.set(key, self.doc.found(f"{m.group(1)}/{m.group(2)}", m.start(), m.end()))
            else:
                self.number(key, m)
        m = self.doc.first(SMOKING, self.doc.ranges(("life_history", "history", "exam", "header", "other",
                                                      "diagnosis")), self.doc.ranges())
        if m:
            self.set("smoking", self.doc.found(phrase(m.group(0)), m.start(), m.end()))

    # ----- ЭКГ -----
    def ecg_record(self) -> list[tuple[int, int]]:
        """Предложения первичной записи ЭКГ: раздел ЭКГ без контрольных записей; иначе — первая строка с ЭКГ."""
        ranges = self.doc.ranges(("ecg",))
        if not ranges:
            for lo, hi in self.doc.sentences(self.doc.ranges()):
                if ECG_WORD.search(self.text, lo, hi) and ECG_CONTENT.search(self.text, lo, hi):
                    line_end = self.text.find("\n", lo)
                    ranges = [(lo, line_end if line_end != -1 else len(self.text))]
                    break
        return [(lo, hi) for lo, hi in self.doc.sentences(ranges) if not ECG_CONTROL.search(self.text, lo, hi)]

    def ecg(self) -> None:
        record = self.ecg_record()
        hits = [(m.start(), m.end(), value) for pattern, value in RHYTHM for m in [self.doc.first(pattern, record)] if m]
        if hits:
            start, end, value = min(hits)
            self.set("ecg_rythm", self.doc.found(value, start, end))
        elif m := self.doc.first(RHYTHM_OTHER, record):
            self.set("ecg_rythm", self.doc.found((m.group(1) or m.group(2)).lower(), m.start(), m.end()))
        self.number("ecg_bpm", self.doc.first(ECG_BPM, record))
        self.set("ecg_elevation", self.binary(ELEVATION, record))
        self.set("ecg_avb", self.binary(AVB, record, self.doc.ranges(("diagnosis",))))

    # ----- ЭхоКГ -----
    def echo(self) -> None:
        scopes = self.scope("echo")
        for key, pattern in ECHO.items():
            self.number(key, self.doc.first(pattern, *scopes))
        for m in self.doc.finditer(MR, scopes[0] + scopes[1]):
            if not self.doc.negated(m.start(), m.end()):
                self.set("echo_mr", self.doc.found(phrase(m.group(0)), m.start(), m.end()))
                break
        for m in self.doc.finditer(ZONE, scopes[0] + scopes[1]):
            if not self.doc.negated(m.start(), m.end()):
                self.set("echo_zone", self.doc.found(phrase(ZONE_TAIL.sub("", m.group(0))), m.start(), m.end()))
                break

    # ----- рентген -----
    def xray(self) -> None:
        ranges = self.doc.ranges(("xray",))
        if not ranges:
            ranges = [s for s in self.doc.sentences(self.doc.ranges()) if XRAY_WORD.search(self.text, *s)]
        m = self.doc.first(re.compile(DATE), ranges)
        if m and (value := date(m.group(0))):
            lo, _ = self.doc.bounds(m.start(), m.end())
            self.set("rg_date", self.doc.found(value, lo, m.end()))
        for lo, hi in self.doc.sentences(ranges):
            m = CONGESTION.search(self.text, lo, hi)
            if not m:
                continue
            if self.doc.negated(m.start(), m.end()):
                self.set("rg_pc", self.doc.found(NOT_FOUND, lo, hi))
                continue
            c = CONCLUSION.search(self.text, lo, m.start())
            start = c.end() if c else lo
            self.set("rg_pc", self.doc.found(phrase(self.text[start:hi]), start, hi))
            break

    # ----- коронарография -----
    def ca(self) -> None:
        section = self.doc.ranges(("ca",))
        sentences = list(self.doc.sentences(section))
        sentences += [s for s in self.doc.sentences(self.doc.ranges(exclude={"therapy", "notes"}))
                      if s not in sentences and CA_WORD.search(self.text, *s)]
        fact = None
        for lo, hi in sentences:
            in_section = any(a <= lo < b for a, b in section)
            if not (in_section or CA_WORD.search(self.text, lo, hi)):
                continue
            if CA_REFUSED.search(self.text, lo, hi):
                fact = fact or self.doc.found("R", lo, hi)
            elif CA_NOT_DONE.search(self.text, lo, hi):
                fact = fact or self.doc.found("N", lo, hi)
            elif CA_WORD.search(self.text, lo, hi) or ARTERY_DESC.search(self.text, lo, hi):
                fact = self.doc.found("Y", lo, hi)
                break
        self.set("ca_fact", fact)
        if not fact or fact.value != "Y":
            return
        m = self.doc.first(re.compile(DATE), [(fact.start, fact.end)], section)
        if m and (value := date(m.group(0))):
            self.set("ca_date", self.doc.found(value, m.start(), m.end()))
        for key, pattern in ARTERIES.items():
            m = self.doc.first(pattern, section, [s for s in sentences])
            if not m:
                continue
            _, end = self.doc.bounds(m.start(), m.end())
            segment = self.text[m.end():end]
            percents = [int(p) for p in PERCENT.findall(segment)]
            grade = ("2" if OCCLUSION.search(segment) else stenosis_grade(max(percents)) if percents
                     else "0" if NO_STENOSIS.search(segment) else None)
            if grade:
                self.set(key, self.doc.found(grade, m.start(), end))

    # ----- лаборатория -----
    def labs(self) -> None:
        scopes = self.scope("labs")
        for key, pattern in LABS.items():
            self.number(key, self.doc.first(pattern, *scopes))
        m = self.doc.first(TROPONIN, *scopes)
        if m:
            word = (m.group(1) or "").lower()
            value = ("положительный" if word.startswith(("положит", "повыш")) else "отрицательный"
                     if word.startswith("отриц") else number(m.group(2)))
            self.set("card_trop", self.doc.found(value, m.start(), m.end()))

    # ----- медикаментозная терапия (назначения при выписке) -----
    def therapy(self) -> None:
        ranges = self.doc.ranges(("therapy",)) or self.doc.ranges(("treatment", "notes", "followup", "other"))
        for lo, hi in ranges:
            for line in re.finditer(r"[^\n]+", self.text[lo:hi]):
                start = lo + line.start() + len(LIST_MARK.match(line.group(0)).group(0))
                self.drug_items(start, lo + line.end())

    def drug_items(self, lo: int, hi: int) -> None:
        """Пункт назначения: от названия препарата до «;»/конца строки/следующего препарата."""
        hits = list(ANY_DRUG.finditer(self.text, lo, hi))
        for i, m in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else hi
            stop = re.search(r"[;\n]|\.(?=\s+[А-ЯЁ])", self.text[m.start():end])
            end = m.start() + stop.start() if stop else end
            item = self.text[m.start():end].rstrip(" ,.;")
            if DRUG_CANCELLED.search(item):
                continue
            for key, pattern in DRUGS.items():
                if key not in self.out and pattern.match(self.text, m.start(), m.end()):
                    self.set(key, self.doc.found(phrase(item), m.start(), m.start() + len(item)))


def extract(seg: Segmented) -> dict[str, Finding]:
    return Extractor(seg).run()
