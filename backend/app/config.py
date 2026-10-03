"""Application settings, loaded from environment variables / the repo-root .env file.

Provider selection is per component, so the project can run entirely on free services:

    LLM  (agent, simulator, judge)  Groq        free tier, GROQ_API_KEY
    STT                             Groq Whisper (free tier) | OpenAI (paid) | mock
    TTS                             browser speech synthesis (free) | OpenAI (paid) | mock

Anything without credentials falls back to a mock, and every mock is reported as such.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

SttProviderName = Literal["groq", "openai", "mock"]
TtsProviderName = Literal["openai", "browser", "mock"]


def _has(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value().strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://salesagent:salesagent@localhost:5433/salesagent"

    # --- Provider selection -----------------------------------------------
    # auto = use whatever has credentials, mock otherwise.  mock = force all mocks.
    # live = require real credentials for the LLM (fail fast if missing).
    provider_mode: Literal["auto", "mock", "live"] = "auto"
    stt_provider: Literal["auto", "groq", "openai", "mock"] = "auto"
    tts_provider: Literal["auto", "openai", "browser", "mock"] = "auto"

    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    openai_api_key: SecretStr | None = None  # optional: only for OpenAI STT / TTS

    # --- Models (verify with `python -m app.cli verify-models`) -------------
    llm_model: str = "qwen/qwen3.8-27b"  # the sales agent (thinking disabled)
    # The simulator and judge default to other models so each has its own quota pool and
    # the judge comes from a different model family than the agent.
    simulator_model: str = "openai/gpt-oss-20b"
    judge_model: str = "openai/gpt-oss-120b"
    stt_model: str | None = None  # default depends on the STT provider
    tts_model: str = "gpt-4o-mini-tts"  # OpenAI TTS only
    tts_voice: str = "ash"
    tts_instructions: str = (
        "Speak in a warm, friendly Indian English accent, like a helpful sales consultant "
        "talking to a business owner. Natural conversational Hinglish pacing."
    )
    stt_prompt: str = (
        "Casual Indian business conversation in Hinglish, written in Roman script. "
        "Example: Hum abhi Excel pe leads manage karte hain, FlowDesk ka demo chahiye."
    )

    # --- LLM call parameters -------------------------------------------------
    llm_temperature: float | None = 0.7
    simulator_temperature: float | None = 0.4
    judge_temperature: float | None = 0.0
    simulator_seed: int = 7
    llm_timeout_s: float = 30.0
    judge_timeout_s: float = 90.0
    llm_max_output_tokens: int = 250
    # Reasoning models (openai/gpt-oss-*) spend output tokens on reasoning, so the judge
    # needs a larger budget.
    judge_max_output_tokens: int = 2000
    reasoning_effort: str = "low"  # for openai/gpt-oss-*; Qwen runs with thinking off ("none")
    # Reasoning tokens count toward max_completion_tokens, so gpt-oss calls get this much
    # extra headroom on top of the visible-reply budget.
    reasoning_token_allowance: int = 800
    llm_max_retries: int = 4  # rate-limit / 5xx retries; backoff time is NOT counted as latency
    # A rate-limit wait longer than this is treated as an exhausted quota (e.g. daily limit).
    max_retry_wait_s: float = 90.0

    # --- Voice / storage ------------------------------------------------------
    max_audio_bytes: int = 10 * 1024 * 1024
    audio_dir: Path = REPO_ROOT / "data" / "audio"

    # --- Benchmark -------------------------------------------------------------
    benchmark_max_turns: int = 8
    benchmark_include_tts: bool = True
    benchmark_concurrency: int = 1

    # ---- derived provider choices -------------------------------------------
    @property
    def has_groq_key(self) -> bool:
        return _has(self.groq_api_key)

    @property
    def has_openai_key(self) -> bool:
        return _has(self.openai_api_key)

    @property
    def llm_is_real(self) -> bool:
        if self.provider_mode == "mock":
            return False
        return self.provider_mode == "live" or self.has_groq_key

    @property
    def effective_stt_provider(self) -> SttProviderName:
        if self.provider_mode == "mock":
            return "mock"
        choice = self.stt_provider
        if choice == "auto":
            if self.has_groq_key:
                return "groq"
            return "openai" if self.has_openai_key else "mock"
        return choice

    @property
    def effective_tts_provider(self) -> TtsProviderName:
        if self.provider_mode == "mock":
            return "mock"
        choice = self.tts_provider
        if choice == "auto":
            if self.has_openai_key:
                return "openai"
            # Free default: speak in the browser. Without a real LLM there is nothing real to speak.
            return "browser" if self.llm_is_real else "mock"
        return choice

    @property
    def effective_stt_model(self) -> str:
        if self.stt_model:
            return self.stt_model
        return (
            "whisper-large-v3-turbo"
            if self.effective_stt_provider == "groq"
            else ("gpt-4o-mini-transcribe")
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
