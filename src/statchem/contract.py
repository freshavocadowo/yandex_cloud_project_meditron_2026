"""The participant template is the single source of structural truth."""
import json
from datetime import datetime
from importlib.resources import files

from jsonschema import Draft202012Validator
from pydantic import ConfigDict, Field, StrictStr, create_model

MISSING = "не указано"
TEMPLATE = json.loads(files("statchem").joinpath("data/template.json").read_text(encoding="utf-8"))
FIELDS = {key: group for group, keys in TEMPLATE.items() for key in keys}
BINARY = {"art_hyper", "atr_fibril", "copd", "dm", "tlt", "ecg_avb", "ecg_elevation"}
NUMERIC = {"bmi", "bpm", "height", "rr", "spo2", "weight", "ecg_bpm", "echo_ef", "echo_lvd", "echo_lvd_2", "crea", "glu", "hb", "ldl", "leucocytes", "thrombocytes", "tot_chol"}
CATEGORIES = {**{f: {"0", "1"} for f in BINARY}, "ca_fact": {"Y", "R", "N"}, "ca_lad": {"0", "1", "2", MISSING}, "rca": {"0", "1", "2", MISSING}, "mi_localisation": {"A", "I", "L", "N"}, "type_acs": {"STEMI", "NSTEMI", "NA"}, "killip": {"1", "2", "3", "4", MISSING}}

groups = {}
for i, (group, fields_) in enumerate(TEMPLATE.items()):
    sub = create_model(f"Group{i}", __config__=ConfigDict(extra="forbid", populate_by_name=True), **{f"field_{key}": (StrictStr, Field(alias=key)) for key in fields_})
    groups[f"group_{i}"] = (sub, Field(alias=group))
Output = create_model("ParticipantOutput", __config__=ConfigDict(extra="forbid", populate_by_name=True), **groups)

# Independently build the schema instead of trusting Pydantic's generated schema.
SCHEMA = {"type": "object", "additionalProperties": False, "required": list(TEMPLATE), "properties": {
    group: {"type": "object", "additionalProperties": False, "required": list(values), "properties": {key: {"type": "string"} for key in values}}
    for group, values in TEMPLATE.items()
}}


def validate_value(field: str, value: str) -> bool:
    import re
    if field not in FIELDS or not isinstance(value, str) or not value.strip():
        return False
    if field in CATEGORIES:
        return value in CATEGORIES[field]
    if value == MISSING:
        return True
    if field.endswith("_date"):
        try:
            return datetime.strptime(value, "%d.%m.%Y").strftime("%d.%m.%Y") == value
        except ValueError:
            return False
    if field in NUMERIC:
        return bool(re.fullmatch(r"\d+(?:\.\d+)?", value))
    if field == "bp":
        return bool(re.fullmatch(r"\d{2,3}/\d{2,3}", value))
    return len(value) <= 1000


def assemble(values: dict[str, str]) -> dict:
    result = {g: {f: values.get(f, MISSING) for f in fs} for g, fs in TEMPLATE.items()}
    if any(not validate_value(f, v) for fs in result.values() for f, v in fs.items()):
        raise ValueError("invalid_field_value")
    if result["коронарография"]["ca_fact"] != "Y":
        for f in ("ca_date", "ca_lad", "rca"):
            if result["коронарография"][f] != MISSING:
                raise ValueError("angiography_without_procedure")
    validated = Output.model_validate(result).model_dump(by_alias=True)
    Draft202012Validator(SCHEMA).validate(validated)
    return validated
