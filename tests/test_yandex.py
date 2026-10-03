import json

import httpx
from openai import OpenAI
import pytest

from statchem.settings import Settings
from statchem.yandex import YandexExtractor


def test_sdk_request_and_structured_response():
    def handler(request):
        payload = json.loads(request.content)
        assert str(request.url) == "https://ai.api.cloud.yandex.net/v1/chat/completions"
        assert request.headers["OpenAI-Project"] == "dummy-folder"
        assert payload["model"] == "gpt://dummy-folder/yandexgpt/5.1"
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
        content = {"candidates": [{"field": "crea", "value": "99", "quote": "Креатинин 99", "section": "labs", "context": "primary"}]}
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0, "model": payload["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(content)}}]})
    extractor = YandexExtractor(Settings(YANDEX_API_KEY="dummy", YANDEX_FOLDER_ID="dummy-folder"))
    extractor.client = OpenAI(api_key="dummy", project="dummy-folder", base_url="https://ai.api.cloud.yandex.net/v1", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert extractor.extract("Креатинин 99", {}).candidates[0].value == "99"


def test_truncated_response_is_error():
    def handler(request):
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0, "model": "test", "choices": [{"index": 0, "finish_reason": "length", "message": {"role": "assistant", "content": '{"candidates":['}}]})
    extractor = YandexExtractor(Settings(YANDEX_API_KEY="dummy", YANDEX_FOLDER_ID="dummy-folder"))
    extractor.client = OpenAI(api_key="dummy", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="incomplete_model_response"):
        extractor.extract("Обезличенный текст", {})
