"""Builds the provider bundle (STT + LLM + TTS) from settings."""

from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.core.errors import ProviderConfigError
from app.domain import RunMode
from app.providers.base import LLMProvider, STTProvider, TTSProvider
from app.providers.groq_llm import GroqLLMProvider, build_groq_client
from app.providers.mock_audio import MockSTTProvider, MockTTSProvider
from app.providers.mock_llm import MockLLMProvider
from app.providers.openai_providers import (
    BrowserTTSProvider,
    OpenAISTTProvider,
    OpenAITTSProvider,
    build_openai_client,
)


@dataclass(frozen=True)
class ProviderBundle:
    stt: STTProvider
    llm: LLMProvider
    tts: TTSProvider
    llm_model: str
    simulator_model: str
    judge_model: str
    stt_model: str
    tts_model: str

    @property
    def run_mode(self) -> RunMode:
        """Benchmark results are 'real' exactly when the LLM (agent, simulator, judge) is real."""
        return RunMode.MOCK if self.llm.is_mock else RunMode.REAL

    @property
    def voice_run_mode(self) -> RunMode:
        """A live voice turn is 'real' only if STT, LLM and TTS are all real services."""
        mocked = (self.stt.is_mock, self.llm.is_mock, self.tts.is_mock)
        return RunMode.MOCK if any(mocked) else RunMode.REAL

    @property
    def llm_models(self) -> dict[str, str]:
        return {
            "agent": self.llm_model,
            "simulator": self.simulator_model,
            "judge": self.judge_model,
        }

    @property
    def times_tts_in_benchmarks(self) -> bool:
        """TTS latency is only meaningful from a real server-side TTS service (or when the
        whole stack is mock, to exercise the code path). Browser TTS is never timed here."""
        if self.tts.client_side:
            return False
        return not self.tts.is_mock or self.llm.is_mock

    @property
    def mock_components(self) -> list[str]:
        return [
            name
            for name, is_mock in (
                ("stt", self.stt.is_mock),
                ("llm", self.llm.is_mock),
                ("tts", self.tts.is_mock),
            )
            if is_mock
        ]

    @property
    def components(self) -> dict[str, dict]:
        return {
            "llm": {"provider": self.llm.name, "model": self.llm_model, "mock": self.llm.is_mock},
            "stt": {"provider": self.stt.name, "model": self.stt_model, "mock": self.stt.is_mock},
            "tts": {
                "provider": self.tts.name,
                "model": self.tts_model,
                "mock": self.tts.is_mock,
                "client_side": self.tts.client_side,
            },
        }


def mock_bundle() -> ProviderBundle:
    return ProviderBundle(
        stt=MockSTTProvider(),
        llm=MockLLMProvider(),
        tts=MockTTSProvider(),
        llm_model="mock-llm",
        simulator_model="mock-llm",
        judge_model="mock-judge",
        stt_model="mock-stt",
        tts_model="mock-tts",
    )


def build_bundle(settings: Settings) -> ProviderBundle:
    mock = mock_bundle()
    if settings.provider_mode == "live" and not settings.has_groq_key:
        raise ProviderConfigError("PROVIDER_MODE=live requires GROQ_API_KEY.")

    llm: LLMProvider = mock.llm
    if settings.llm_is_real:
        llm = GroqLLMProvider(build_groq_client(settings), settings)

    stt: STTProvider = mock.stt
    stt_name = settings.effective_stt_provider
    if stt_name == "groq":
        stt = OpenAISTTProvider(build_groq_client(settings), settings, name="groq")
    elif stt_name == "openai":
        stt = OpenAISTTProvider(build_openai_client(settings), settings, name="openai")

    tts: TTSProvider = mock.tts
    tts_name = settings.effective_tts_provider
    if tts_name == "openai":
        tts = OpenAITTSProvider(build_openai_client(settings), settings)
    elif tts_name == "browser":
        tts = BrowserTTSProvider()

    return ProviderBundle(
        stt=stt,
        llm=llm,
        tts=tts,
        llm_model=settings.llm_model if not llm.is_mock else mock.llm_model,
        simulator_model=settings.simulator_model if not llm.is_mock else mock.simulator_model,
        judge_model=settings.judge_model if not llm.is_mock else mock.judge_model,
        stt_model="mock-stt" if stt.is_mock else settings.effective_stt_model,
        tts_model=(
            "mock-tts"
            if tts.is_mock
            else "browser-speech-synthesis" if tts.client_side else settings.tts_model
        ),
    )


@lru_cache
def get_providers() -> ProviderBundle:
    """FastAPI dependency / default entry point. Tests override this."""
    return build_bundle(get_settings())
