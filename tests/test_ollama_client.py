from __future__ import annotations

import requests

from memory_system.ollama_client import ChatMessage, UniversalLLMClient


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

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
