import time

import pytest

from app.api import benchmark as benchmark_api
from app.config import get_settings
from app.main import app
from app.providers.factory import get_providers
from tests.helpers import EmptySTT, FailingSTT, FailingTTS, TimeoutLLM, with_providers


def voice(client, wav, **data):
    data.setdefault("prompt_variant", "persona")
    return client.post(
        "/api/voice/respond", files={"audio": ("a.wav", wav, "audio/wav")}, data=data
    )


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["llm_provider"] == "mock"


def test_config_exposes_variants_and_mock_flag(client):
    body = client.get("/api/config").json()
    assert body["is_mock"] is True
    assert [v["id"] for v in body["prompt_variants"]] == ["zero_shot", "few_shot", "persona"]


def test_scenarios_endpoint(client):
    assert len(client.get("/api/scenarios").json()) == 25


# ------------------------------------------------------------ conversations
def test_create_and_fetch_conversation(client):
    r = client.post("/api/conversations", json={"prompt_variant": "few_shot"})
    assert r.status_code == 201
    created = r.json()
    assert created["prompt_variant"] == "few_shot" and created["turns"] == []
    fetched = client.get(f"/api/conversations/{created['id']}")
    assert fetched.status_code == 200 and fetched.json()["id"] == created["id"]


def test_create_conversation_for_scenario(client):
    r = client.post(
        "/api/conversations", json={"prompt_variant": "persona", "scenario_id": "disc-excel"}
    )
    assert r.status_code == 201
    assert r.json()["scenario"]["id"] == "disc-excel"


def test_create_conversation_validation(client):
    bad = client.post("/api/conversations", json={"prompt_variant": "nonsense"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"
    assert client.post("/api/conversations", json={}).status_code == 422
    missing = client.post(
        "/api/conversations", json={"prompt_variant": "persona", "scenario_id": "nope"}
    )
    assert missing.status_code == 404


def test_unknown_conversation_is_404(client):
    r = client.get("/api/conversations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.get("/api/conversations/not-a-uuid").status_code == 422


# ------------------------------------------------------------------ voice
def test_voice_respond_full_pipeline(client, wav_bytes):
    r = voice(client, wav_bytes)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] and body["response_text"]
    assert body["mock_mode"] is True
    lat = body["latency"]
    assert set(lat) == {"stt_ms", "llm_ms", "tts_ms", "total_ms"}
    assert lat["total_ms"] >= lat["llm_ms"] >= 0
    audio = client.get(body["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"


def test_voice_conversation_state_is_preserved_across_turns(client, wav_bytes):
    first = voice(client, wav_bytes).json()
    cid = first["conversation_id"]
    second = voice(
        client, wav_bytes, conversation_id=cid, transcript_override="Price zyada hai yaar"
    ).json()
    assert second["conversation_id"] == cid
    detail = client.get(f"/api/conversations/{cid}").json()
    assert [t["speaker"] for t in detail["turns"]] == ["customer", "agent", "customer", "agent"]
    assert detail["turns"][2]["text"] == "Price zyada hai yaar"
    assert detail["turns"][1]["latency"]["stt_ms"] is not None
    assert detail["latency_summary"]["total_ms"] > 0


def test_voice_cannot_switch_strategy_mid_conversation(client, wav_bytes):
    cid = voice(client, wav_bytes).json()["conversation_id"]
    r = voice(client, wav_bytes, conversation_id=cid, prompt_variant="zero_shot")
    assert r.status_code == 409


def test_voice_unknown_conversation(client, wav_bytes):
    r = voice(client, wav_bytes, conversation_id="00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_voice_rejects_unsupported_format(client):
    r = client.post(
        "/api/voice/respond",
        files={"audio": ("a.txt", b"hello world" * 50, "text/plain")},
        data={"prompt_variant": "persona"},
    )
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_audio_format"


def test_voice_rejects_invalid_audio(client):
    r = client.post(
        "/api/voice/respond",
        files={"audio": ("a.wav", b"", "audio/wav")},
        data={"prompt_variant": "persona"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_audio"
    corrupt = client.post(
        "/api/voice/respond",
        files={"audio": ("a.wav", b"not really audio" * 50, "audio/wav")},
        data={"prompt_variant": "persona"},
    )
    assert corrupt.status_code == 422


def test_voice_rejects_oversized_audio(client, wav_bytes):
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"max_audio_bytes": 100}
    )
    try:
        r = voice(client, wav_bytes)
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert r.status_code == 413 and r.json()["error"]["code"] == "audio_too_large"


def test_voice_requires_prompt_variant(client, wav_bytes):
    r = client.post("/api/voice/respond", files={"audio": ("a.wav", wav_bytes, "audio/wav")})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "override,status,code",
    [
        ({"stt": FailingSTT()}, 502, "stt_failed"),
        ({"llm": TimeoutLLM()}, 504, "llm_timeout"),
        ({"stt": EmptySTT()}, 422, "invalid_audio"),
    ],
)
def test_voice_provider_failures_return_safe_errors(
    client, providers, wav_bytes, override, status, code
):
    app.dependency_overrides[get_providers] = lambda: with_providers(providers, **override)
    r = voice(client, wav_bytes)
    assert r.status_code == status
    error = r.json()["error"]
    assert error["code"] == code
    assert "Traceback" not in r.text and 'File "' not in r.text


def test_failed_turn_persists_nothing(client, providers, wav_bytes):
    cid = voice(client, wav_bytes).json()["conversation_id"]
    app.dependency_overrides[get_providers] = lambda: with_providers(providers, llm=TimeoutLLM())
    assert voice(client, wav_bytes, conversation_id=cid).status_code == 504
    app.dependency_overrides[get_providers] = lambda: providers
    assert len(client.get(f"/api/conversations/{cid}").json()["turns"]) == 2


def test_tts_failure_degrades_to_text_only(client, providers, wav_bytes):
    app.dependency_overrides[get_providers] = lambda: with_providers(providers, tts=FailingTTS())
    r = voice(client, wav_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["audio_url"] is None and body["warnings"] == ["tts_failed"]
    assert body["latency"]["tts_ms"] is None and body["response_text"]


def test_audio_endpoint_blocks_path_traversal(client):
    assert client.get("/api/audio/..%2F..%2F.env").status_code == 404
    assert client.get("/api/audio/nonexistent.wav").status_code == 404


def test_unhandled_errors_do_not_leak_internals(client, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("secret internal detail sk-abc123")

    monkeypatch.setattr("app.api.system.load_scenarios", boom)
    r = client.get("/api/scenarios")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in r.text and "sk-abc123" not in r.text


# ---------------------------------------------------- evaluations / benchmark
def wait_for_benchmark(client, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/api/benchmark").json()
        if not status["is_running"]:
            return status
        time.sleep(0.1)
    raise AssertionError("benchmark did not finish")


def test_summary_before_any_benchmark(client):
    body = client.get("/api/evaluations/summary").json()
    assert body["benchmark_run"] is None and body["conversations"] == 0
    assert client.get("/api/evaluations").json() == {"items": [], "total": 0}


def test_benchmark_run_then_evaluation_retrieval(client):
    started = client.post(
        "/api/benchmark/run",
        json={"scenario_ids": ["disc-excel", "price-expensive", "intent-demo"], "max_turns": 6},
    )
    assert started.status_code == 202
    assert started.json()["total_conversations"] == 9
    assert started.json()["run_mode"] == "mock"
    status = wait_for_benchmark(client)
    assert status["latest_run"]["status"] == "completed"
    assert status["latest_run"]["completed_conversations"] == 9

    evals = client.get("/api/evaluations").json()
    assert evals["total"] == 9
    item = evals["items"][0]
    assert {"overall_score", "goal_completion_score", "reasoning", "prompt_variant"} <= set(item)

    only_persona = client.get("/api/evaluations?prompt_variant=persona").json()
    assert only_persona["total"] == 3
    assert all(i["prompt_variant"] == "persona" for i in only_persona["items"])
    assert client.get("/api/evaluations?category=price_objection").json()["total"] == 3

    summary = client.get("/api/evaluations/summary").json()
    assert summary["is_mock"] is True
    assert summary["conversations"] == 9 and summary["scenarios"] == 3
    assert [v["prompt_variant"] for v in summary["by_variant"]] == [
        "zero_shot",
        "few_shot",
        "persona",
    ]
    assert len(summary["scenario_matrix"]) == 3
    assert all(len(r["cells"]) == 3 for r in summary["scenario_matrix"])
    assert summary["by_variant"][0]["latency"]["p95_total_ms"] is not None

    detail = client.get(f"/api/conversations/{item['id']}").json()
    assert detail["evaluation"]["reasoning"] and detail["scenario"]["id"]
    assert detail["run_mode"] == "mock"


def test_conversation_list_filters(client):
    client.post(
        "/api/benchmark/run", json={"scenario_ids": ["disc-excel"], "variants": ["persona"]}
    )
    wait_for_benchmark(client)
    client.post("/api/conversations", json={"prompt_variant": "zero_shot"})
    assert client.get("/api/conversations").json()["total"] == 2
    assert client.get("/api/conversations?source=benchmark").json()["total"] == 1
    assert client.get("/api/conversations?prompt_variant=zero_shot").json()["total"] == 1
    assert client.get("/api/conversations?min_score=6").status_code == 422
    assert client.get("/api/conversations?sort=score_desc&limit=1").json()["items"]


def test_benchmark_rejects_unknown_scenario_and_bad_turns(client):
    assert client.post("/api/benchmark/run", json={"scenario_ids": ["nope"]}).status_code == 422
    assert client.post("/api/benchmark/run", json={"max_turns": 99}).status_code == 422


def test_only_one_benchmark_at_a_time(client, monkeypatch):
    import threading

    release = threading.Event()
    original = benchmark_api.runner.execute_run

    def slow(*args, **kwargs):
        release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(benchmark_api.runner, "execute_run", slow)
    first = client.post(
        "/api/benchmark/run", json={"scenario_ids": ["disc-excel"], "variants": ["persona"]}
    )
    assert first.status_code == 202
    second = client.post("/api/benchmark/run", json={"scenario_ids": ["disc-excel"]})
    assert second.status_code == 409
    release.set()
    wait_for_benchmark(client)


def test_voice_with_browser_tts_asks_the_client_to_speak(client, providers, wav_bytes):
    from app.providers.openai_providers import BrowserTTSProvider

    app.dependency_overrides[get_providers] = lambda: with_providers(
        providers, tts=BrowserTTSProvider()
    )
    r = voice(client, wav_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["audio_url"] is None and body["speak_client_side"] is True
    assert body["warnings"] == [] and body["latency"]["tts_ms"] is None
    assert body["mock_components"] == ["stt", "llm"]  # TTS is real (browser), the rest are mocks


def test_config_reports_components(client):
    body = client.get("/api/config").json()
    assert set(body["components"]) == {"llm", "stt", "tts"}
    assert body["components"]["llm"]["mock"] is True and body["llm_is_mock"] is True
    assert body["mock_components"] == ["stt", "llm", "tts"]


def test_real_benchmark_is_blocked_when_models_fail_verification(client, providers, monkeypatch):
    from dataclasses import replace

    from app.api import benchmark as benchmark_module
    from app.providers.model_check import ModelVerificationError
    from tests.helpers import RecordingLLM

    real_like = replace(providers, llm=RecordingLLM(["x"]))  # is_mock is False
    app.dependency_overrides[get_providers] = lambda: real_like

    def refuse(*_a, **_k):
        raise ModelVerificationError("Model verification failed (judge 'x': missing).")

    monkeypatch.setattr(benchmark_module, "ensure_verified", refuse)
    r = client.post("/api/benchmark/run", json={"scenario_ids": ["disc-excel"]})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "model_verification_failed"
    assert client.get("/api/benchmark").json()["latest_run"] is None  # nothing was started


def test_mock_benchmark_skips_verification(client, monkeypatch):
    from app.api import benchmark as benchmark_module

    def boom(*_a, **_k):
        raise AssertionError("verification must not run for mock providers")

    monkeypatch.setattr(benchmark_module, "ensure_verified", boom)
    r = client.post(
        "/api/benchmark/run", json={"scenario_ids": ["disc-excel"], "variants": ["persona"]}
    )
    assert r.status_code == 202
    wait_for_benchmark(client)
