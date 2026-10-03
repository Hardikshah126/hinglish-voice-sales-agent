"""Model verification preflight, tested against a fake provider API."""

import httpx
import pytest
from openai import OpenAI

from app.config import Settings
from app.providers import model_check
from app.providers.factory import ProviderBundle, build_bundle, mock_bundle
from app.providers.groq_llm import GroqLLMProvider
from app.providers.model_check import (
    ModelVerificationError,
    ensure_verified,
    verify_models,
)

SETTINGS = Settings(
    _env_file=None,
    provider_mode="auto",
    groq_api_key="gsk-test",
    llm_model="llama-a",
    simulator_model="llama-b",
    judge_model="openai/gpt-oss-x",
)
GROQ_MODELS = ["llama-a", "llama-b", "openai/gpt-oss-x", "whisper-large-v3-turbo"]


def S(**kw) -> Settings:
    """Settings for provider-selection tests: ignore .env and the suite-wide PROVIDER_MODE=mock."""
    kw.setdefault("provider_mode", "auto")
    return Settings(_env_file=None, **kw)


def fake_groq(models=GROQ_MODELS, chat_status=200) -> OpenAI:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/models"):
            return httpx.Response(
                200, json={"object": "list", "data": [{"id": m, "object": "model"} for m in models]}
            )
        if chat_status != 200:
            return httpx.Response(chat_status, json={"error": {"message": "x", "code": "y"}})
        return httpx.Response(
            200,
            headers={
                "x-ratelimit-limit-requests": "1000",
                "x-ratelimit-limit-tokens": "8000",
                "x-ratelimit-remaining-requests": "999",
                "x-ratelimit-remaining-tokens": "7990",
            },
            json={
                "id": "x", "object": "chat.completion", "created": 0, "model": "m",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": '{"ok": true}'}}],
            },
        )  # fmt: skip

    return OpenAI(
        api_key="gsk-test",
        base_url=SETTINGS.groq_base_url,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


@pytest.fixture
def bundle() -> ProviderBundle:
    return build_bundle(SETTINGS)  # real Groq LLM + Groq STT + browser TTS; no network on build


@pytest.fixture(autouse=True)
def _clear_cache():
    model_check.clear_cache()


def test_all_configured_models_verified_and_limits_reported(bundle):
    report = verify_models(SETTINGS, bundle, groq_client=fake_groq())
    assert report.passed
    by_component = {c.component: c for c in report.checks}
    assert {"agent", "simulator", "judge", "stt"} <= set(by_component)
    assert all(by_component[c].status == "ok" for c in ("agent", "simulator", "judge", "stt"))
    assert "smoke call ok" in by_component["judge"].detail
    assert by_component["tts"].status == "skipped"  # browser TTS
    limit = report.limits[0]
    assert limit.requests_limit == "1000" and limit.tokens_limit == "8000"


def test_missing_model_is_reported_and_fails(bundle):
    report = verify_models(
        SETTINGS, bundle, groq_client=fake_groq(models=["llama-a", "whisper-large-v3-turbo"])
    )
    assert not report.passed
    missing = {c.component for c in report.checks if c.status == "missing"}
    assert missing == {"simulator", "judge"}


def test_smoke_failure_is_an_error_without_provider_details(bundle):
    report = verify_models(SETTINGS, bundle, groq_client=fake_groq(chat_status=400))
    assert not report.passed
    bad = [c for c in report.checks if c.status == "error"]
    assert bad and all("smoke call failed" in c.detail for c in bad)
    assert not any("gsk-test" in c.detail for c in report.checks)


def test_listing_failure_marks_every_model_as_error(bundle):
    def handler(r):
        return httpx.Response(
            401, json={"error": {"message": "bad key", "code": "invalid_api_key"}}
        )

    client = OpenAI(
        api_key="gsk-test",
        base_url=SETTINGS.groq_base_url,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    report = verify_models(SETTINGS, bundle, groq_client=client)
    assert not report.passed
    assert all("rejected" in c.detail for c in report.checks if c.status == "error")


def test_no_smoke_only_lists(bundle):
    report = verify_models(SETTINGS, bundle, smoke=False, groq_client=fake_groq(chat_status=500))
    assert report.passed and not report.limits


def test_mock_bundle_has_nothing_to_verify():
    report = verify_models(S(), mock_bundle())
    assert report.passed
    assert {c.status for c in report.checks} == {"skipped"}


def test_openai_audio_models_are_checked_when_used():
    settings = S(openai_api_key="sk-x", tts_provider="openai")
    bundle = build_bundle(settings)  # llm mock, stt openai, tts openai

    def handler(r):
        return httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "gpt-4o-mini-transcribe", "object": "model"}]},
        )

    client = OpenAI(
        api_key="sk-x",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    report = verify_models(settings, bundle, openai_client=client)
    statuses = {c.component: c.status for c in report.checks if c.provider == "openai"}
    assert statuses == {"stt": "ok", "tts": "missing"}  # gpt-4o-mini-tts absent from the fake list


def test_unknown_tts_voice_warns():
    settings = S(openai_api_key="sk-x", tts_provider="openai", tts_voice="zzz")
    client = OpenAI(
        api_key="sk-x",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={"object": "list", "data": [
                        {"id": m, "object": "model"} for m in ("gpt-4o-mini-transcribe", "gpt-4o-mini-tts")
                    ]},
                )
            )
        ),
        max_retries=0,
    )  # fmt: skip
    report = verify_models(settings, build_bundle(settings), openai_client=client)
    assert report.passed  # a warning does not block
    assert any(c.status == "warning" and "zzz" in c.model for c in report.checks)


def test_ensure_verified_raises_and_caches(monkeypatch, bundle):
    calls = {"n": 0}
    real = model_check.verify_models

    def counting(settings, b, smoke=True, **kw):
        calls["n"] += 1
        return real(settings, b, smoke, groq_client=fake_groq(), **kw)

    monkeypatch.setattr(model_check, "verify_models", counting)
    ensure_verified(SETTINGS, bundle)
    ensure_verified(SETTINGS, bundle)
    assert calls["n"] == 1  # second call served from cache

    model_check.clear_cache()
    monkeypatch.setattr(
        model_check,
        "verify_models",
        lambda s, b, smoke=True, **kw: real(s, b, smoke, groq_client=fake_groq(models=[]), **kw),
    )
    with pytest.raises(ModelVerificationError) as exc:
        ensure_verified(SETTINGS, bundle)
    assert "missing" in exc.value.message


def test_bundle_uses_groq_provider_for_all_llm_calls(bundle):
    assert isinstance(bundle.llm, GroqLLMProvider)
    assert bundle.llm_models == {
        "agent": "llama-a",
        "simulator": "llama-b",
        "judge": "openai/gpt-oss-x",
    }
