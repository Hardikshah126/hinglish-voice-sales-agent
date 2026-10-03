"""STT / TTS providers.

`OpenAISTTProvider` speaks the OpenAI audio API, which Groq also exposes (same request
shape), so it serves both: pass a Groq client for the free tier, an OpenAI client otherwise.
`OpenAITTSProvider` needs an OpenAI key (paid). `BrowserTTSProvider` is the free option:
the server returns text and the browser speaks it with the Web Speech API.
"""

import time

import openai
from openai import OpenAI

from app.config import Settings
from app.core.errors import ProviderConfigError, STTError, TTSError
from app.core.logging import get_logger
from app.providers.base import STTProvider, STTResult, TTSProvider, TTSResult

log = get_logger(__name__)


def build_openai_client(settings: Settings) -> OpenAI:
    if not settings.has_openai_key or settings.openai_api_key is None:
        raise ProviderConfigError("OPENAI_API_KEY is not set.")
    return OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.llm_timeout_s,
        max_retries=2,
    )


class OpenAISTTProvider(STTProvider):
    def __init__(self, client: OpenAI, settings: Settings, name: str = "openai"):
        self.name = name
        self._client = client
        self._settings = settings

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> STTResult:
        model = self._settings.effective_stt_model
        start = time.perf_counter()
        try:
            result = self._client.audio.transcriptions.create(
                model=model,
                file=(filename, audio, content_type),
                prompt=self._settings.stt_prompt,
            )
        except openai.APIError as exc:
            log.error(
                "stt_error",
                extra={"provider": self.name, "model": model, "error_type": type(exc).__name__},
            )
            raise STTError() from exc
        latency_ms = (time.perf_counter() - start) * 1000
        return STTResult(text=(result.text or "").strip(), latency_ms=latency_ms, model=model)


class OpenAITTSProvider(TTSProvider):
    name = "openai"

    def __init__(self, client: OpenAI, settings: Settings):
        self._client = client
        self._settings = settings

    def synthesize(self, text: str) -> TTSResult:
        model = self._settings.tts_model
        kwargs: dict = {
            "model": model,
            "voice": self._settings.tts_voice,
            "input": text,
            "response_format": "mp3",
        }
        # Style instructions are only supported by the gpt-4o-*-tts family.
        if model.startswith("gpt-4o") and self._settings.tts_instructions:
            kwargs["instructions"] = self._settings.tts_instructions

        start = time.perf_counter()
        try:
            response = self._client.audio.speech.create(**kwargs)
            audio = response.content
        except openai.APIError as exc:
            log.error("tts_error", extra={"model": model, "error_type": type(exc).__name__})
            raise TTSError() from exc
        latency_ms = (time.perf_counter() - start) * 1000
        return TTSResult(
            audio=audio,
            content_type="audio/mpeg",
            extension="mp3",
            latency_ms=latency_ms,
            model=model,
        )


class BrowserTTSProvider(TTSProvider):
    """Free TTS: the server produces no audio; the browser speaks the reply text."""

    name = "browser"
    client_side = True

    def synthesize(self, text: str) -> TTSResult:  # pragma: no cover - never called
        raise TTSError("Browser TTS is synthesised client-side.")
