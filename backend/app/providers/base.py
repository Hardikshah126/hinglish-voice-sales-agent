"""Provider interfaces. The rest of the app depends only on these abstractions.

Every provider times its own network call with a monotonic clock (time.perf_counter) and
reports the elapsed milliseconds, so latency numbers are always measured, never estimated.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Task = Literal["agent", "simulator", "judge"]


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class LLMRequest:
    system: str
    messages: list[ChatMessage]
    task: Task
    temperature: float | None = None
    max_output_tokens: int | None = None
    json_mode: bool = False
    seed: int | None = None
    model: str | None = None
    timeout_s: float | None = None
    reasoning_effort: str | None = None
    # Structured context (scenario, transcript...). Only the mock provider reads this;
    # real providers see nothing but `system` and `messages`.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    latency_ms: float
    model: str


@dataclass(frozen=True)
class STTResult:
    text: str
    latency_ms: float
    model: str


@dataclass(frozen=True)
class TTSResult:
    audio: bytes
    content_type: str
    extension: str
    latency_ms: float
    model: str


class LLMProvider(ABC):
    name: str
    is_mock: bool = False

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse: ...


class STTProvider(ABC):
    name: str
    is_mock: bool = False

    @abstractmethod
    def transcribe(self, audio: bytes, filename: str, content_type: str) -> STTResult: ...


class TTSProvider(ABC):
    name: str
    is_mock: bool = False
    # True when speech is synthesised in the user's browser instead of on the server.
    client_side: bool = False

    @abstractmethod
    def synthesize(self, text: str) -> TTSResult: ...
