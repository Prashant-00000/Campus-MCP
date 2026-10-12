import httpx
import pytest

from agent.llm import LLMProvider


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        return next(self.responses)


def response(status, headers=None, data=None):
    request = httpx.Request("POST", "http://test/v1/chat/completions")
    return httpx.Response(status, headers=headers or {}, json=data, request=request)


def success_response():
    return response(200, data={
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    })


def provider(max_retries=3):
    return LLMProvider(
        model_name="test-model",
        provider="ollama",
        base_url="http://test/v1",
        enable_cache=False,
        max_retries=max_retries,
    )


def test_numeric_retry_after_then_success(monkeypatch):
    waits = []
    fake_client = FakeClient([
        response(429, headers={"retry-after": "1"}, data={"error": "busy"}),
        success_response(),
    ])
    monkeypatch.setattr("agent.llm.httpx.Client", lambda **_kwargs: fake_client)
    monkeypatch.setattr("agent.llm.time.sleep", waits.append)

    result = provider().generate([], [])
    assert result.content == "ok"
    assert waits == [2]
    assert result.retry_count == 1


def test_non_numeric_retry_after_uses_bounded_backoff(monkeypatch):
    waits = []
    fake_client = FakeClient([
        response(429, headers={"retry-after": "tomorrow"}, data={"error": "busy"}),
        success_response(),
    ])
    monkeypatch.setattr("agent.llm.httpx.Client", lambda **_kwargs: fake_client)
    monkeypatch.setattr("agent.llm.time.sleep", waits.append)

    provider().generate([], [])
    assert waits == [7]


def test_long_daily_limit_retry_raises_without_sleep(monkeypatch):
    sleeps = []
    fake_client = FakeClient([
        response(429, headers={"retry-after": "120"}, data={"error": "daily limit"}),
    ])
    monkeypatch.setattr("agent.llm.httpx.Client", lambda **_kwargs: fake_client)
    monkeypatch.setattr("agent.llm.time.sleep", sleeps.append)

    with pytest.raises(RuntimeError, match="resumable|resume after"):
        provider().generate([], [])
    assert sleeps == []


def test_server_error_retries_then_succeeds(monkeypatch):
    waits = []
    fake_client = FakeClient([
        response(503, data={"error": "unavailable"}),
        success_response(),
    ])
    monkeypatch.setattr("agent.llm.httpx.Client", lambda **_kwargs: fake_client)
    monkeypatch.setattr("agent.llm.time.sleep", waits.append)

    result = provider().generate([], [])
    assert result.content == "ok"
    assert waits == [1]
