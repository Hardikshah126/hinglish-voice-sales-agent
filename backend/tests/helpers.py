"""Test doubles for provider failure injection and request capture."""

from dataclasses import replace

from app.core.errors import LLMQuotaExhaustedError, LLMTimeoutError, STTError, TTSError
from app.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    STTProvider,
    STTResult,
    TTSProvider,
    TTSResult,
)
from app.providers.factory import ProviderBundle


class RecordingLLM(LLMProvider):
    """Returns scripted replies (cycling) and records every request it receives."""

    name = "recording"

    def __init__(self, replies: list[str]):
        self.replies = replies
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        text = self.replies[(len(self.requests) - 1) % len(self.replies)]
        return LLMResponse(text=text, latency_ms=1.0, model="recording")


class TimeoutLLM(LLMProvider):
    name = "timeout"

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise LLMTimeoutError()


class FailingSTT(STTProvider):
    name = "failing"

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> STTResult:
        raise STTError()


class EmptySTT(STTProvider):
    name = "empty"

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> STTResult:
        return STTResult(text="   ", latency_ms=1.0, model="empty")


class FailingTTS(TTSProvider):
    name = "failing"

    def synthesize(self, text: str) -> TTSResult:
        raise TTSError()


def with_providers(bundle: ProviderBundle, **overrides) -> ProviderBundle:
    return replace(bundle, **overrides)


class QuotaLLM(LLMProvider):
    """Wraps another LLM and raises a quota-exhausted error after `allow` successful calls."""

    name = "quota"

    def __init__(self, inner: LLMProvider, allow: int):
        self.inner = inner
        self.allow = allow
        self.calls = 0
        self.is_mock = inner.is_mock

    def generate(self, request: LLMRequest) -> LLMResponse:
        if self.calls >= self.allow:
            raise LLMQuotaExhaustedError("Groq quota for model 'x' is exhausted. Resume later.")
        self.calls += 1
        return self.inner.generate(request)
