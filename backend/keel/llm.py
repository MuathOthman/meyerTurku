"""Provider-agnostic LLM adapter. JSON-schema outputs only.

The LLM may name room categories and rephrase findings. It never measures and never
decides a verdict. Nothing else in Keel imports a provider directly.

Configuration (environment, or a .env file in this folder or any parent):
  KEEL_LLM_PROVIDER  openai | gemini | ollama | none. Defaults to openai if its key is set.
  api_chatgpt        OpenAI key
  api_gemini         Google AI Studio key
  KEEL_LLM_MODEL     model override
  OLLAMA_URL         defaults to http://localhost:11434, for local or EU-hosted models
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

import certifi

DEFAULT_MODELS = {"openai": "gpt-5.5", "gemini": "gemini-3.8-flash", "ollama": "mistral"}
OPENAI_FALLBACKS = ["gpt-5.4-mini", "gpt-4o"]
# Tried in order when the first model is overloaded or unavailable.
GEMINI_FALLBACKS = ["gemini-3.5-flash", "gemini-flash-latest"]
RETRYABLE_STATUS = {404, 429, 500, 503, 504}


class LLMError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLM(Protocol):
    name: str

    def complete_json(self, prompt: str, schema: dict[str, Any], images: list[bytes] | None = None) -> Any: ...


def read_env_file(start: Path | None = None) -> dict[str, str]:
    """Values from the nearest .env file, walking up from start. Does not touch os.environ."""
    folder = (start or Path(__file__).resolve()).parent if (start or Path(__file__)).is_file() else start
    for directory in [folder, *folder.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            values = {}
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip("\"'")
            return values
    return {}


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: float = 60.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        # Some Python installs ship without root certificates, so bring our own.
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        # The body explains the failure; the key travels in a header so it cannot appear here.
        raise LLMError(
            f"LLM request failed: HTTP {error.code}: {error.read()[:300]!r}",
            retryable=error.code in RETRYABLE_STATUS,
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise LLMError(f"LLM request failed: {error}", retryable=True) from error


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini accepts an OpenAPI subset: drop keywords it rejects."""
    converted = {k: v for k, v in schema.items() if k != "additionalProperties"}
    if "properties" in converted:
        converted["properties"] = {k: _to_gemini_schema(v) for k, v in converted["properties"].items()}
    if "items" in converted:
        converted["items"] = _to_gemini_schema(converted["items"])
    return converted


class GeminiLLM:
    def __init__(self, api_key: str, model: str, fallbacks: list[str] | None = None):
        self.api_key = api_key
        self.model = model
        self.fallbacks = fallbacks or []
        self.name = f"gemini:{model}"

    def complete_json(self, prompt: str, schema: dict[str, Any], images: list[bytes] | None = None) -> Any:
        """Try the main model, then each fallback, so one overloaded model does not stop a run."""
        last_error: LLMError | None = None
        for model in [self.model, *self.fallbacks]:
            try:
                return self._call(model, prompt, schema, images)
            except LLMError as error:
                if not error.retryable:
                    raise
                last_error = error
        raise last_error

    def _call(self, model: str, prompt: str, schema: dict[str, Any], images: list[bytes] | None) -> Any:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        image_parts = [
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image).decode()}}
            for image in images or []
        ]
        payload = {
            "contents": [{"role": "user", "parts": [*image_parts, {"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": _to_gemini_schema(schema),
            },
        }
        data = _post_json(url, payload, {"x-goog-api-key": self.api_key}, timeout=90.0 if images else 30.0)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as error:
            raise LLMError(f"unexpected Gemini response: {str(data)[:300]}") from error


def _to_openai_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict mode needs every property required and no additional properties."""
    converted = dict(schema)
    if "properties" in converted:
        converted["properties"] = {k: _to_openai_schema(v) for k, v in converted["properties"].items()}
        converted["required"] = list(converted["properties"])
        converted["additionalProperties"] = False
    if "items" in converted:
        converted["items"] = _to_openai_schema(converted["items"])
    return converted


class OpenAILLM:
    def __init__(self, api_key: str, model: str, fallbacks: list[str] | None = None):
        self.api_key = api_key
        self.model = model
        self.fallbacks = fallbacks or []
        self.name = f"openai:{model}"

    def complete_json(self, prompt: str, schema: dict[str, Any], images: list[bytes] | None = None) -> Any:
        """Try the main model, then each fallback, so one busy model does not stop a run."""
        last_error: LLMError | None = None
        for model in [self.model, *self.fallbacks]:
            try:
                return self._call(model, prompt, schema, images)
            except LLMError as error:
                if not error.retryable:
                    raise
                last_error = error
        raise last_error

    def _call(self, model: str, prompt: str, schema: dict[str, Any], images: list[bytes] | None) -> Any:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images or []:
            encoded = base64.b64encode(image).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "high"}})
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "keel_answer", "strict": True, "schema": _to_openai_schema(schema)},
            },
        }
        data = _post_json(
            "https://api.openai.com/v1/chat/completions",
            payload,
            {"Authorization": f"Bearer {self.api_key}"},
            timeout=180.0 if images else 60.0,
        )
        try:
            return json.loads(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise LLMError(f"unexpected OpenAI response: {str(data)[:300]}") from error


class OllamaLLM:
    """Runs on your own machine or server, so no drawing data leaves it."""

    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model
        self.name = f"ollama:{model}"

    def complete_json(self, prompt: str, schema: dict[str, Any], images: list[bytes] | None = None) -> Any:
        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            # Needs a vision-capable model, set through KEEL_LLM_MODEL.
            message["images"] = [base64.b64encode(image).decode() for image in images]
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [message],
        }
        data = _post_json(f"{self.url}/api/chat", payload, {}, timeout=180.0)
        try:
            return json.loads(data["message"]["content"])
        except (KeyError, json.JSONDecodeError) as error:
            raise LLMError(f"unexpected Ollama response: {str(data)[:300]}") from error


class CachedLLM:
    """Remembers answers on disk. Repeat runs cost no quota, and demos do not depend on the network."""

    def __init__(self, inner: LLM, folder: Path):
        self.inner = inner
        self.name = inner.name
        self.folder = folder

    def complete_json(self, prompt: str, schema: dict[str, Any], images: list[bytes] | None = None) -> Any:
        digest = hashlib.sha256()
        digest.update(self.name.encode())
        digest.update(prompt.encode())
        digest.update(json.dumps(schema, sort_keys=True).encode())
        for image in images or []:
            digest.update(image)
        path = self.folder / f"{digest.hexdigest()}.json"
        if path.is_file():
            return json.loads(path.read_text())
        answer = self.inner.complete_json(prompt, schema, images)
        self.folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(answer))
        return answer


def get_llm() -> LLM | None:
    """The configured LLM, or None. Keel works without one, and unknown rooms go to review."""
    llm = _configured_llm()
    if llm is None:
        return None
    cache = Path(__file__).resolve().parents[1] / "data" / "processed" / "llm_cache"
    return CachedLLM(llm, cache)


def _configured_llm() -> LLM | None:
    env = {**read_env_file(), **os.environ}
    openai_key = env.get("api_chatgpt") or env.get("OPENAI_API_KEY")
    provider = env.get("KEEL_LLM_PROVIDER", "openai" if openai_key else "gemini").lower()
    if provider == "none":
        return None
    model = env.get("KEEL_LLM_MODEL") or DEFAULT_MODELS.get(provider)
    if provider == "openai":
        return OpenAILLM(openai_key, model, OPENAI_FALLBACKS) if openai_key else None
    if provider == "gemini":
        key = env.get("api_gemini") or env.get("GEMINI_API_KEY")
        return GeminiLLM(key, model, GEMINI_FALLBACKS) if key else None
    if provider == "ollama":
        return OllamaLLM(env.get("OLLAMA_URL", "http://localhost:11434"), model)
    raise LLMError(f"unknown KEEL_LLM_PROVIDER {provider!r}")
