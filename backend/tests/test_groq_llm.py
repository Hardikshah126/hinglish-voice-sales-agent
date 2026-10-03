"""Groq LLM provider tests against a fake HTTP transport (real `openai` SDK, no network)."""

import json

import httpx
import pytest
from openai import OpenAI

from app.config import Settings
from app.core.errors import (
    LLMError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    ProviderConfigError,
)
from app.providers.base import ChatMessage, LLMRequest
from app.providers.groq_llm import GroqLLMProvider, build_groq_client

SETTINGS = Settings(
    _env_file=None,
    groq_api_key="gsk-test-not-real",
    llm_model="test-llama",
    llm_max_retries=3,
    max_retry_wait_s=30,
)


def client_for(handler) -> OpenAI:
    return OpenAI(
        api_key="gsk-test-not-real",
        base_url=SETTINGS.groq_base_url,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


def reply(text: str | None = "ok", finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish,
                    "message": {"role": "assistant", "content": text},
                }
            ],
        },
    )


def error(status: int, code: str = "x", headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"message": "secret detail", "code": code}}, headers=headers
    )


def req(task="agent", **kw) -> LLMRequest:
    return LLMRequest(
        system="SYS", messages=[ChatMessage("user", "Hello")], task=task, **kw  # type: ignore[arg-type]
    )


class Sleeper:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def provider(handler, sleeper=None) -> GroqLLMProvider:
    return GroqLLMProvider(client_for(handler), SETTINGS, sleep=sleeper or Sleeper())


def test_client_targets_groq_and_never_retries_internally():
    client = build_groq_client(Settings(_env_file=None, groq_api_key="gsk-x"))
    assert str(client.base_url).startswith("https://api.groq.com/openai/v1")
    assert client.max_retries == 0


def test_missing_key_is_a_config_error():
    with pytest.raises(ProviderConfigError):
        build_groq_client(Settings(_env_file=None, groq_api_key=None))


def test_request_payload_for_a_plain_model():
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["path"] = r.url.path
        seen["body"] = json.loads(r.content)
        seen["auth"] = r.headers["authorization"]
        return reply(" Haan ji. ")

    out = provider(handler).generate(req(temperature=0.3, seed=7, json_mode=True))
    body = seen["body"]
    assert seen["path"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer gsk-test-not-real"
    assert body["model"] == "test-llama"  # from settings
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert body["temperature"] == 0.3 and body["seed"] == 7
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == SETTINGS.llm_max_output_tokens
    assert "reasoning_effort" not in body and "include_reasoning" not in body
    assert out.text == "Haan ji." and out.latency_ms >= 0 and out.model == "test-llama"


def test_gpt_oss_gets_reasoning_controls_and_judge_budget():
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(json.loads(r.content))
        return reply('{"ok": true}')

    provider(handler).generate(req(task="judge", model="openai/gpt-oss-120b", json_mode=True))
    assert seen["reasoning_effort"] == "low"
    assert seen["include_reasoning"] is False
    assert seen["max_completion_tokens"] == SETTINGS.judge_max_output_tokens


def test_qwen_runs_with_thinking_off_and_hidden_reasoning():
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(json.loads(r.content))
        return reply("ok")

    provider(handler).generate(req(model="qwen/qwen3.8-27b", max_output_tokens=250))
    assert seen["reasoning_effort"] == "none"
    assert seen["reasoning_format"] == "hidden"
    assert seen["max_completion_tokens"] == 250  # no reasoning allowance without reasoning


def test_gpt_oss_gets_headroom_for_reasoning_tokens_on_short_replies():
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(json.loads(r.content))
        return reply("ok")

    provider(handler).generate(
        req(task="simulator", model="openai/gpt-oss-20b", max_output_tokens=200)
    )
    assert seen["max_completion_tokens"] == 200 + SETTINGS.reasoning_token_allowance
    assert seen["reasoning_effort"] == "low"


def test_think_blocks_are_stripped():
    out = provider(lambda r: reply("<think>hmm</think>Namaste")).generate(req())
    assert out.text == "Namaste"


def test_rate_limit_is_retried_and_wait_is_not_counted_as_latency():
    calls = {"n": 0}
    sleeper = Sleeper()

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return error(429, headers={"retry-after": "7"}) if calls["n"] == 1 else reply("done")

    out = provider(handler, sleeper).generate(req())
    assert out.text == "done" and calls["n"] == 2
    assert sleeper.calls == [7.0]  # honoured retry-after
    assert out.latency_ms < 1000  # the 7 s wait is excluded from measured latency


def test_server_errors_are_retried_with_backoff():
    calls = {"n": 0}
    sleeper = Sleeper()

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return error(503) if calls["n"] < 3 else reply("recovered")

    assert provider(handler, sleeper).generate(req()).text == "recovered"
    assert sleeper.calls == [1.0, 2.0]


def test_rate_limit_retries_are_bounded():
    sleeper = Sleeper()
    with pytest.raises(LLMRateLimitError) as exc:
        provider(lambda r: error(429, headers={"retry-after": "1"}), sleeper).generate(req())
    assert not isinstance(exc.value, LLMQuotaExhaustedError)
    assert len(sleeper.calls) == SETTINGS.llm_max_retries


def test_long_retry_after_means_quota_exhausted_and_is_not_waited_out():
    sleeper = Sleeper()
    with pytest.raises(LLMQuotaExhaustedError) as exc:
        provider(lambda r: error(429, headers={"retry-after": "7200"}), sleeper).generate(
            req(model="llama-x")
        )
    assert sleeper.calls == []
    assert "llama-x" in exc.value.message and "Resume" in exc.value.message


def test_timeout_is_not_retried():
    sleeper = Sleeper()
    calls = {"n": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=r)

    with pytest.raises(LLMTimeoutError):
        provider(handler, sleeper).generate(req())
    assert calls["n"] == 1 and sleeper.calls == []


def test_auth_error_does_not_leak_the_key_or_provider_body():
    with pytest.raises(ProviderConfigError) as exc:
        provider(lambda r: error(401, "invalid_api_key")).generate(req())
    assert "gsk-test" not in exc.value.message and "secret detail" not in exc.value.message


def test_unknown_model_points_to_verify_models():
    with pytest.raises(ProviderConfigError) as exc:
        provider(lambda r: error(404, "model_not_found")).generate(req(model="nope-1"))
    assert "nope-1" in exc.value.message and "verify-models" in exc.value.message


def test_json_validate_failed_is_a_response_error_so_callers_can_retry():
    with pytest.raises(LLMResponseError):
        provider(lambda r: error(400, "json_validate_failed")).generate(req(json_mode=True))


def test_other_bad_requests_are_generic_errors():
    with pytest.raises(LLMError) as exc:
        provider(lambda r: error(400, "invalid_request")).generate(req())
    assert "secret detail" not in exc.value.message


def test_empty_content_is_a_response_error():
    with pytest.raises(LLMResponseError):
        provider(lambda r: reply(None, finish="length")).generate(req())
