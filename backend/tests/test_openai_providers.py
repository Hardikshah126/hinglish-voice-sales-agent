"""Exercises the real OpenAI-style STT/TTS providers against a fake HTTP transport (no network, no key).

The real `openai` client is used, so request paths, payload shapes and exception mapping
are verified exactly as they would be on the wire.
"""

import json

import httpx
import pytest
from openai import OpenAI

from app.config import Settings
from app.core.errors import STTError, TTSError
from app.providers.openai_providers import (
    BrowserTTSProvider,
    OpenAISTTProvider,
    OpenAITTSProvider,
)

SETTINGS = Settings(
    _env_file=None,
    openai_api_key="sk-test-not-real",
    llm_model="test-llm",
    stt_model="test-stt",
    tts_model="gpt-4o-test-tts",
    tts_voice="test-voice",
)


def client_for(handler) -> OpenAI:
    return OpenAI(
        api_key="sk-test-not-real",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


def test_stt_request_payload():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = req.content
        return httpx.Response(200, json={"text": "Hum Excel use karte hain."})

    stt = OpenAISTTProvider(client_for(handler), SETTINGS)
    result = stt.transcribe(b"RIFFfakeaudio", "audio.wav", "audio/wav")

    assert seen["path"].endswith("/audio/transcriptions")
    assert b"test-stt" in seen["body"] and b"audio.wav" in seen["body"]
    assert SETTINGS.stt_prompt.encode() in seen["body"]  # Roman-script Hinglish hint
    assert result.text == "Hum Excel use karte hain." and result.model == "test-stt"


def test_stt_failure_maps_to_stt_error():
    with pytest.raises(STTError):
        OpenAISTTProvider(client_for(lambda r: httpx.Response(500)), SETTINGS).transcribe(
            b"x", "a.wav", "audio/wav"
        )


def test_tts_request_payload_and_instructions():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=b"ID3fakemp3", headers={"content-type": "audio/mpeg"})

    out = OpenAITTSProvider(client_for(handler), SETTINGS).synthesize("Namaste")
    assert seen["path"].endswith("/audio/speech")
    assert seen["body"]["model"] == "gpt-4o-test-tts"
    assert seen["body"]["voice"] == "test-voice" and seen["body"]["input"] == "Namaste"
    assert seen["body"]["instructions"] == SETTINGS.tts_instructions
    assert out.audio == b"ID3fakemp3" and out.extension == "mp3"


def test_tts_skips_instructions_for_models_that_do_not_support_them():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return httpx.Response(200, content=b"ID3x")

    settings = SETTINGS.model_copy(update={"tts_model": "tts-1"})
    OpenAITTSProvider(client_for(handler), settings).synthesize("Namaste")
    assert "instructions" not in seen


def test_tts_failure_maps_to_tts_error():
    with pytest.raises(TTSError):
        OpenAITTSProvider(client_for(lambda r: httpx.Response(500)), SETTINGS).synthesize("x")


def test_groq_stt_uses_the_free_whisper_model_through_the_same_provider():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = req.content
        return httpx.Response(200, json={"text": "Price zyada hai."})

    settings = Settings(_env_file=None, provider_mode="auto", groq_api_key="gsk-test-not-real")
    client = OpenAI(
        api_key="gsk-test-not-real",
        base_url=settings.groq_base_url,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    out = OpenAISTTProvider(client, settings, name="groq").transcribe(
        b"RIFFx", "a.wav", "audio/wav"
    )
    assert seen["path"] == "/openai/v1/audio/transcriptions"
    assert b"whisper-large-v3-turbo" in seen["body"]
    assert out.text == "Price zyada hai." and out.model == "whisper-large-v3-turbo"


def test_browser_tts_is_client_side_and_not_a_mock():
    tts = BrowserTTSProvider()
    assert tts.client_side and not tts.is_mock
    with pytest.raises(TTSError):
        tts.synthesize("x")
