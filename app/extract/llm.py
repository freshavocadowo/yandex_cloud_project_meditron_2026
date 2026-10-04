"""LLM-страховка для полей, которые правила не подтвердили цитатой.

Любой OpenAI-совместимый Chat Completions API: vLLM на GPU-ВМ Yandex Cloud или
YandexGPT (https://llm.api.cloud.yandex.net/v1, модель gpt://<folder>/yandexgpt/latest).
Включается переменными окружения LLM_BASE_URL и LLM_MODEL (+ LLM_API_KEY).
Ответ — строго по JSON-схеме (response_format json_schema), temperature=0.
Значение LLM принимается, только если оно проходит контракт и его цитата найдена
в тексте; иначе после 3 попыток поле остаётся за правилами (rules-only fallback).
"""
from dataclasses import dataclass
import json
import os
import urllib.request

from ..schema import NOT_FOUND, check_value, default
from .prompts import SYSTEM, repair_prompt, response_schema, user_prompt
from .rules import Finding

ATTEMPTS = 3


class LLMError(RuntimeError):
    pass


@dataclass
class LLMClient:
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 120.0

    def chat(self, messages: list[dict], schema: dict) -> str:
        body = {"model": self.model, "messages": messages, "temperature": 0,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "extraction", "schema": schema, "strict": True}}}
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:  # сеть, HTTP, формат ответа — всё означает «LLM недоступна»
            raise LLMError(type(exc).__name__) from exc


def from_env() -> LLMClient | None:
    base_url, model = os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_MODEL")
    if not (base_url and model):
        return None
    return LLMClient(base_url, model, os.environ.get("LLM_API_KEY", ""), float(os.environ.get("LLM_TIMEOUT", 120)))


def parse(raw: str, fields: list[str], text: str) -> tuple[dict[str, Finding], list[str]]:
    """Разбор ответа: Finding для подтверждённых значений и список ошибок для повторного запроса."""
    from ..validate import locate  # validate импортирует rules; локальный импорт без цикла

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}, ["ответ не является JSON"]
    if not isinstance(data, dict):
        return {}, ["корень ответа должен быть объектом"]
    found, errors = {}, []
    for key in fields:
        item = data.get(key)
        if not isinstance(item, dict) or not isinstance(item.get("value"), str):
            errors.append(f"{key}: нет value")
            continue
        value, evidence = item["value"].strip(), str(item.get("evidence") or "")
        if value in (NOT_FOUND, default(key)) and not evidence:
            continue
        if (code := check_value(key, value)) is not None:
            errors.append(f"{key}: значение «{value}» не соответствует формату ({code})")
            continue
        span = locate(text, evidence)
        if span is None:
            errors.append(f"{key}: цитата не найдена в тексте")
            continue
        found[key] = Finding(value, text[span[0]:span[1]], span[0], span[1], "llm")
    return found, errors


def fill_missing(client: LLMClient, text: str, findings: dict[str, Finding]) -> tuple[dict[str, Finding], list[str]]:
    """Merger: правило с цитатой > LLM с цитатой > значение по умолчанию."""
    missing = [key for key, f in findings.items() if f.source == "default"]
    if not missing:
        return findings, []
    schema = response_schema(missing)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_prompt(text, missing)}]
    found: dict[str, Finding] = {}
    for _ in range(ATTEMPTS):
        try:
            raw = client.chat(messages, schema)
        except LLMError as exc:
            return findings, [f"llm_unavailable:{exc}"]
        found, errors = parse(raw, missing, text)
        if not errors:
            break
        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": repair_prompt(errors)}]
    else:
        return {**findings, **found}, ["llm_partial"]
    return {**findings, **found}, []
