from __future__ import annotations

import requests

from memory_system.ollama_client import ChatMessage, UniversalLLMClient


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def json(self) -> dict:
        return self._payload


def test_anthropic_retries_transient_529(monkeypatch):
    calls: list[int] = []
    responses = [
        _DummyResponse(529, {"error": {"type": "overloaded_error"}}),
        _DummyResponse(200, {"content": [{"type": "text", "text": "ok"}]}),
    ]

    def fake_post(*args, **kwargs):
        calls.append(1)
        return responses[len(calls) - 1]

    monkeypatch.setattr("memory_system.ollama_client.requests.post", fake_post)
    monkeypatch.setattr("memory_system.ollama_client.time.sleep", lambda *_args, **_kwargs: None)

    client = UniversalLLMClient(provider="anthropic", base_url="https://api.anthropic.com", api_key="test")
    out = client.chat(
        model="claude-sonnet-4-20250514",
        messages=[ChatMessage(role="user", content="hello")],
    )

    assert out == "ok"
    assert len(calls) == 2


def test_anthropic_does_not_retry_non_transient_http_error(monkeypatch):
    calls: list[int] = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return _DummyResponse(400, {"error": {"type": "invalid_request_error"}})

    monkeypatch.setattr("memory_system.ollama_client.requests.post", fake_post)
    monkeypatch.setattr("memory_system.ollama_client.time.sleep", lambda *_args, **_kwargs: None)

    client = UniversalLLMClient(provider="anthropic", base_url="https://api.anthropic.com", api_key="test")

    try:
        client.chat(
            model="claude-sonnet-4-20250514",
            messages=[ChatMessage(role="user", content="hello")],
        )
    except requests.exceptions.HTTPError as exc:
        assert exc.response is not None
        assert exc.response.status_code == 400
    else:
        raise AssertionError("Expected an HTTPError for a non-transient Anthropic failure.")

    assert len(calls) == 1


def test_github_models_uses_expected_endpoint_and_headers(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(url, *, json, timeout, headers):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        captured["headers"] = headers
        return _DummyResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("memory_system.ollama_client.requests.post", fake_post)

    client = UniversalLLMClient(
        provider="github_models",
        base_url="https://models.github.ai/inference",
        api_key="gh-token",
    )
    out = client.chat(
        model="openai/gpt-5",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.3,
    )

    assert out == "ok"
    assert captured["url"] == "https://models.github.ai/inference/chat/completions"
    assert captured["json"] == {
        "model": "openai/gpt-5",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.3,
    }
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer gh-token"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_github_models_retries_without_temperature_when_model_rejects_it(monkeypatch):
    calls: list[dict[str, object]] = []
    responses = [
        _DummyResponse(
            400,
            {
                "error": {
                    "message": "Unsupported value: 'temperature' does not support 0 with this model. Only the default (1) value is supported.",
                    "type": "invalid_request_error",
                    "param": "temperature",
                    "code": "unsupported_value",
                }
            },
        ),
        _DummyResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
    ]

    def fake_post(url, *, json, timeout, headers):
        calls.append({"url": url, "json": json, "headers": headers})
        return responses[len(calls) - 1]

    monkeypatch.setattr("memory_system.ollama_client.requests.post", fake_post)

    client = UniversalLLMClient(
        provider="github_models",
        base_url="https://models.github.ai/inference",
        api_key="gh-token",
    )
    out = client.chat(
        model="openai/gpt-5",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.0,
    )

    assert out == "ok"
    assert len(calls) == 2
    assert calls[0]["json"] == {
        "model": "openai/gpt-5",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.0,
    }
    assert calls[1]["json"] == {
        "model": "openai/gpt-5",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_github_models_retries_transient_429(monkeypatch):
    calls: list[dict[str, object]] = []
    responses = [
        _DummyResponse(429, {"error": {"message": "rate limited"}}, headers={"Retry-After": "0"}),
        _DummyResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
    ]

    def fake_post(url, *, json, timeout, headers):
        calls.append({"url": url, "json": json, "headers": headers})
        return responses[len(calls) - 1]

    monkeypatch.setattr("memory_system.ollama_client.requests.post", fake_post)
    monkeypatch.setattr("memory_system.ollama_client.time.sleep", lambda *_args, **_kwargs: None)

    client = UniversalLLMClient(
        provider="github_models",
        base_url="https://models.github.ai/inference",
        api_key="gh-token",
    )
    out = client.chat(
        model="DeepSeek-R1",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
    )

    assert out == "ok"
    assert len(calls) == 2
    assert calls[0]["json"] == {
        "model": "DeepSeek-R1",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.7,
    }


def test_github_models_from_env_uses_github_token_fallback(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "github_models")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-env-token")

    client = UniversalLLMClient.from_env()

    assert client.provider == "github_models"
    assert client.base_url == "https://models.github.ai/inference"
    assert client.api_key == "gh-env-token"


def test_ollama_from_env_uses_ollama_host_fallback(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11435")

    client = UniversalLLMClient.from_env()

    assert client.provider == "ollama"
    assert client.base_url == "http://127.0.0.1:11435"
    assert client.api_key is None


def test_github_models_normalizes_base_url_without_inference_suffix():
    client = UniversalLLMClient(
        provider="github",
        base_url="https://models.github.ai",
        api_key="gh-token",
    )

    assert client.provider == "github_models"
    assert client.base_url == "https://models.github.ai/inference"
