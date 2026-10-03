import io
import logging
import wave

import pytest

from app.config import Settings
from app.core.errors import (
    AudioTooLargeError,
    InvalidAudioError,
    ProviderConfigError,
    UnsupportedAudioError,
)
from app.core.logging import JsonFormatter
from app.providers.factory import build_bundle, mock_bundle
from app.providers.groq_llm import GroqLLMProvider
from app.providers.mock_audio import CANNED_TRANSCRIPTS, MockSTTProvider, MockTTSProvider
from app.voice.audio_validation import validate_audio

WAV = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 300


def S(**kw) -> Settings:
    """Settings for provider-selection tests: ignore .env and the suite-wide PROVIDER_MODE=mock."""
    kw.setdefault("provider_mode", "auto")
    return Settings(_env_file=None, **kw)


def test_no_keys_selects_mock_providers():
    bundle = build_bundle(S())
    assert bundle.run_mode.value == "mock" and bundle.voice_run_mode.value == "mock"
    assert bundle.llm.is_mock and bundle.stt.is_mock and bundle.tts.is_mock
    assert bundle.mock_components == ["stt", "llm", "tts"]


def test_groq_key_alone_gives_a_fully_free_real_stack_without_network():
    settings = S(groq_api_key="gsk-test-not-real")
    bundle = build_bundle(settings)
    assert isinstance(bundle.llm, GroqLLMProvider) and bundle.llm.name == "groq"
    assert bundle.stt.name == "groq" and not bundle.stt.is_mock
    assert bundle.tts.name == "browser" and bundle.tts.client_side and not bundle.tts.is_mock
    assert bundle.run_mode.value == "real" and bundle.voice_run_mode.value == "real"
    assert bundle.mock_components == []
    assert bundle.stt_model == "whisper-large-v3-turbo"  # free Groq Whisper by default
    assert bundle.llm_models == {
        "agent": settings.llm_model,
        "simulator": settings.simulator_model,
        "judge": settings.judge_model,
    }


def test_openai_key_alone_only_enables_openai_audio():
    bundle = build_bundle(S(openai_api_key="sk-test-not-real"))
    assert bundle.llm.is_mock and bundle.run_mode.value == "mock"
    assert bundle.stt.name == "openai" and bundle.tts.name == "openai"
    assert bundle.stt_model == "gpt-4o-mini-transcribe" and bundle.tts_model == "gpt-4o-mini-tts"
    assert bundle.mock_components == ["llm"]


def test_groq_llm_with_openai_audio_when_both_keys_exist():
    bundle = build_bundle(S(groq_api_key="gsk-x", openai_api_key="sk-x", stt_provider="openai"))
    assert bundle.llm.name == "groq" and bundle.stt.name == "openai" and bundle.tts.name == "openai"


def test_stt_and_tts_can_be_forced_to_mock_while_the_llm_is_real():
    bundle = build_bundle(S(groq_api_key="gsk-x", stt_provider="mock", tts_provider="mock"))
    assert bundle.run_mode.value == "real"  # benchmark results depend on the LLM only
    assert bundle.voice_run_mode.value == "mock"  # a live voice turn is not fully real
    assert bundle.mock_components == ["stt", "tts"]
    assert not bundle.times_tts_in_benchmarks  # mock TTS latency must not pollute real runs


def test_browser_tts_is_never_timed_in_benchmarks():
    assert not build_bundle(S(groq_api_key="gsk-x")).times_tts_in_benchmarks
    assert mock_bundle().times_tts_in_benchmarks  # all-mock runs still exercise the TTS path


def test_provider_mode_mock_overrides_keys():
    bundle = build_bundle(S(groq_api_key="gsk-x", openai_api_key="sk-x", provider_mode="mock"))
    assert bundle.mock_components == ["stt", "llm", "tts"]


def test_live_mode_without_groq_key_is_a_config_error():
    with pytest.raises(ProviderConfigError):
        build_bundle(S(provider_mode="live"))


def test_blank_keys_count_as_missing():
    settings = S(groq_api_key="  ", openai_api_key="")
    assert not settings.has_groq_key and not settings.has_openai_key
    assert build_bundle(settings).llm.is_mock


def test_defaults_are_current_documented_models():
    s = S()
    assert s.llm_model == "qwen/qwen3.8-27b"
    assert s.judge_model == "openai/gpt-oss-120b" and s.judge_model != s.llm_model
    assert s.effective_stt_model == "gpt-4o-mini-transcribe"  # no keys: openai/mock branch
    assert S(groq_api_key="x").effective_stt_model == "whisper-large-v3-turbo"
    assert S(stt_model="custom").effective_stt_model == "custom"


def test_mock_stt_is_deterministic():
    stt = MockSTTProvider()
    first = stt.transcribe(WAV, "a.wav", "audio/wav")
    assert first.text in CANNED_TRANSCRIPTS
    assert stt.transcribe(WAV, "a.wav", "audio/wav").text == first.text
    assert first.latency_ms >= 0


def test_mock_tts_returns_playable_wav():
    result = MockTTSProvider().synthesize("Haan ji, bataiye kya madad chahiye?")
    assert result.content_type == "audio/wav" and result.extension == "wav"
    with wave.open(io.BytesIO(result.audio)) as wav:
        assert wav.getnframes() > 0
        assert wav.getnchannels() == 1


def test_valid_audio_formats_are_accepted():
    assert validate_audio(WAV, "audio/wav", 10_000).extension == "wav"
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 300
    assert validate_audio(webm, "audio/webm;codecs=opus", 10_000).extension == "webm"
    mp3 = b"ID3" + b"\x00" * 300
    assert validate_audio(mp3, "audio/mpeg", 10_000).extension == "mp3"
    m4a = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 300
    assert validate_audio(m4a, "audio/mp4", 10_000).extension == "m4a"


def test_empty_and_tiny_audio_is_invalid():
    with pytest.raises(InvalidAudioError):
        validate_audio(b"", "audio/wav", 10_000)
    with pytest.raises(InvalidAudioError):
        validate_audio(b"RIFF", "audio/wav", 10_000)


def test_oversized_audio_is_rejected():
    with pytest.raises(AudioTooLargeError):
        validate_audio(WAV, "audio/wav", 100)


def test_unsupported_content_type_is_rejected():
    with pytest.raises(UnsupportedAudioError):
        validate_audio(WAV, "text/plain", 10_000)
    with pytest.raises(UnsupportedAudioError):
        validate_audio(WAV, None, 10_000)


def test_corrupted_audio_with_valid_content_type_is_rejected():
    with pytest.raises(InvalidAudioError):
        validate_audio(b"this is not audio" * 40, "audio/wav", 10_000)


def test_log_formatter_redacts_secrets():
    record = logging.LogRecord("t", logging.INFO, "", 0, "event", (), None)
    record.api_key = "sk-secret"
    record.openai_api_key = "sk-secret"
    record.conversation_id = "abc"
    out = JsonFormatter().format(record)
    assert "sk-secret" not in out
    assert "abc" in out


def test_settings_repr_hides_api_key():
    settings = S(openai_api_key="sk-super-secret", groq_api_key="gsk-secret")
    for secret in ("sk-super-secret", "gsk-secret"):
        assert secret not in repr(settings)
        assert secret not in str(settings.model_dump())


def test_env_example_is_valid_and_defaults_to_mock():
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / ".env.example"
    settings = Settings(_env_file=example, provider_mode="auto")
    assert not settings.has_groq_key and not settings.has_openai_key  # keys are blank
    assert build_bundle(settings).mock_components == ["stt", "llm", "tts"]
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.llm_model == S().llm_model  # example matches defaults
    with pytest.raises(ProviderConfigError):
        build_bundle(settings.model_copy(update={"provider_mode": "live"}))
