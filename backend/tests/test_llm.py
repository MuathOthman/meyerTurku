import pytest

from keel import llm as llm_module
from keel.llm import GeminiLLM, LLMError, OpenAILLM, _to_gemini_schema, _to_openai_schema, read_env_file


def test_schema_conversion_drops_unsupported_keys():
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"a": {"type": "array", "items": {"type": "string", "additionalProperties": False}}}}
    converted = _to_gemini_schema(schema)
    assert "additionalProperties" not in converted
    assert "additionalProperties" not in converted["properties"]["a"]["items"]


def test_read_env_file_walks_up_and_strips_quotes(tmp_path):
    (tmp_path / ".env").write_text('# comment\napi_gemini="abc"\n')
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert read_env_file(nested) == {"api_gemini": "abc"}


def reply(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_gemini_falls_back_when_model_is_overloaded(monkeypatch):
    called = []

    def fake_post(url, payload, headers, timeout=60.0):
        called.append(url)
        if "busy" in url:
            raise LLMError("HTTP 503", retryable=True)
        return reply('{"ok": true}')

    monkeypatch.setattr(llm_module, "_post_json", fake_post)
    assert GeminiLLM("k", "busy", ["spare"]).complete_json("p", {"type": "object"}) == {"ok": True}
    assert len(called) == 2


def test_gemini_does_not_retry_a_bad_key(monkeypatch):
    def fake_post(url, payload, headers, timeout=60.0):
        raise LLMError("HTTP 403", retryable=False)

    monkeypatch.setattr(llm_module, "_post_json", fake_post)
    with pytest.raises(LLMError):
        GeminiLLM("k", "main", ["spare"]).complete_json("p", {"type": "object"})


def test_api_key_is_sent_in_a_header_not_the_url(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, timeout=60.0):
        seen.update(url=url, headers=headers)
        return reply("{}")

    monkeypatch.setattr(llm_module, "_post_json", fake_post)
    GeminiLLM("secret", "main").complete_json("p", {"type": "object"})
    assert "secret" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "secret"


def test_openai_schema_is_strict_at_every_level():
    schema = {"type": "object", "properties": {"a": {"type": "array", "items": {
        "type": "object", "properties": {"b": {"type": "string"}, "c": {"type": "string"}}, "required": ["b"]}}}}
    item = _to_openai_schema(schema)["properties"]["a"]["items"]
    assert item["additionalProperties"] is False
    assert sorted(item["required"]) == ["b", "c"]


def openai_reply(text):
    return {"choices": [{"message": {"content": text}}]}


def test_openai_sends_key_in_header_and_image_as_data_url(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, timeout=60.0):
        seen.update(url=url, payload=payload, headers=headers)
        return openai_reply('{"ok": true}')

    monkeypatch.setattr(llm_module, "_post_json", fake_post)
    answer = OpenAILLM("secret", "main").complete_json("p", {"type": "object"}, images=[b"jpeg"])
    assert answer == {"ok": True}
    assert "secret" not in seen["url"]
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["payload"]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openai_falls_back_when_busy_but_not_on_a_bad_key(monkeypatch):
    def busy(url, payload, headers, timeout=60.0):
        if payload["model"] == "busy":
            raise LLMError("HTTP 429", retryable=True)
        return openai_reply('{"ok": true}')

    monkeypatch.setattr(llm_module, "_post_json", busy)
    assert OpenAILLM("k", "busy", ["spare"]).complete_json("p", {"type": "object"}) == {"ok": True}

    def denied(url, payload, headers, timeout=60.0):
        raise LLMError("HTTP 401", retryable=False)

    monkeypatch.setattr(llm_module, "_post_json", denied)
    with pytest.raises(LLMError):
        OpenAILLM("k", "main", ["spare"]).complete_json("p", {"type": "object"})


def test_openai_is_the_default_when_its_key_is_set(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_module, "read_env_file", lambda start=None: {"api_chatgpt": "k", "api_gemini": "g"})
    monkeypatch.delenv("KEEL_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("KEEL_LLM_MODEL", raising=False)
    assert llm_module._configured_llm().name.startswith("openai:")
    monkeypatch.setenv("KEEL_LLM_PROVIDER", "gemini")
    assert llm_module._configured_llm().name.startswith("gemini:")
