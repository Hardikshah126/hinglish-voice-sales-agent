"""Preflight verification of every configured model against the live provider APIs.

A real benchmark must not start with a wrong model name or an unsupported parameter, so:
  1. list each provider's models (GET /models) and confirm each configured name exists;
  2. smoke-test each LLM through the real provider code path (same parameters as the
     benchmark, JSON mode for the judge), which also catches parameter incompatibilities;
  3. read the account's rate-limit headers so the run can be sized against the quota.

Nothing here prints or returns API keys, and provider error bodies are not echoed.
"""

import time
from dataclasses import dataclass, field

import openai
from openai import OpenAI

from app.config import Settings
from app.core.errors import AppError, ProviderConfigError
from app.core.logging import get_logger
from app.providers.base import ChatMessage, LLMRequest
from app.providers.factory import ProviderBundle
from app.providers.groq_llm import GroqLLMProvider, build_groq_client
from app.providers.openai_providers import build_openai_client

log = get_logger(__name__)

# Built-in voices listed in the OpenAI text-to-speech docs (checked 2026-10-03). The API has
# no endpoint to list voices, so this is a static check that only produces a warning.
OPENAI_TTS_VOICES = {
    "alloy", "ash", "ballad", "coral", "echo", "fable", "nova",
    "onyx", "sage", "shimmer", "verse", "marin", "cedar",
}  # fmt: skip

CACHE_TTL_S = 15 * 60
_cache: dict[str, tuple[float, "VerificationReport"]] = {}


class ModelVerificationError(AppError):
    status_code = 503
    code = "model_verification_failed"
    default_message = (
        "Configured models could not be verified. Run `python -m app.cli verify-models`."
    )


@dataclass
class Check:
    component: str  # agent | simulator | judge | stt | tts
    provider: str
    model: str
    status: str  # ok | missing | error | warning | skipped
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "skipped", "warning"}


@dataclass
class RateLimits:
    model: str
    requests_limit: str | None = None  # Groq: per-day request limit
    tokens_limit: str | None = None  # Groq: per-minute token limit
    requests_remaining: str | None = None
    tokens_remaining: str | None = None


@dataclass
class VerificationReport:
    checks: list[Check] = field(default_factory=list)
    limits: list[RateLimits] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    def models(self) -> dict[str, str]:
        return {c.component: c.model for c in self.checks}


def _list_ids(client: OpenAI) -> set[str]:
    return {m.id for m in client.models.list()}


def _smoke_request(task: str, model: str, json_mode: bool) -> LLMRequest:
    return LLMRequest(
        system='You are a connectivity probe. Reply with only this JSON: {"ok": true}',
        messages=[ChatMessage("user", "ping")],
        task=task,  # type: ignore[arg-type]
        temperature=0.0,
        max_output_tokens=None,
        json_mode=json_mode,
        model=model,
    )


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return "the API key was rejected"
    if isinstance(exc, openai.RateLimitError):
        return "rate limited (quota may be exhausted)"
    if isinstance(exc, openai.APIConnectionError):
        return "could not reach the API"
    if isinstance(exc, openai.APIStatusError):
        return f"HTTP {exc.status_code} ({exc.code or 'error'})"
    if isinstance(exc, AppError):
        return exc.message
    return type(exc).__name__


def _verify_groq(
    settings: Settings,
    bundle: ProviderBundle,
    smoke: bool,
    report: VerificationReport,
    client: OpenAI | None,
):
    wanted: list[tuple[str, str]] = []
    if not bundle.llm.is_mock:
        wanted += [
            ("agent", settings.llm_model),
            ("simulator", settings.simulator_model),
            ("judge", settings.judge_model),
        ]
    if bundle.stt.name == "groq":
        wanted.append(("stt", settings.effective_stt_model))
    if not wanted:
        return

    client = client or build_groq_client(settings)
    try:
        available = _list_ids(client)
    except Exception as exc:
        for component, model in wanted:
            report.checks.append(Check(component, "groq", model, "error", _safe_error(exc)))
        return

    provider = GroqLLMProvider(client, settings)
    probed: set[str] = set()
    for component, model in wanted:
        if model not in available:
            report.checks.append(
                Check(component, "groq", model, "missing", "not in Groq's current model list")
            )
            continue
        if component == "stt" or not smoke:
            report.checks.append(Check(component, "groq", model, "ok", "listed by the API"))
            continue
        # One smoke call per (model, task) so judge-specific parameters are exercised.
        task = "judge" if component == "judge" else "agent"
        try:
            request = _smoke_request(task, model, json_mode=component != "agent")
            started = time.perf_counter()
            raw = client.chat.completions.with_raw_response.create(
                **provider.build_kwargs(request, model)
            )
            elapsed = (time.perf_counter() - started) * 1000
            if not raw.parse().choices:
                raise ProviderConfigError("empty response")
            report.checks.append(
                Check(component, "groq", model, "ok", f"listed; smoke call ok ({elapsed:.0f} ms)")
            )
            if model not in probed:
                probed.add(model)
                h = raw.headers
                report.limits.append(
                    RateLimits(
                        model=model,
                        requests_limit=h.get("x-ratelimit-limit-requests"),
                        tokens_limit=h.get("x-ratelimit-limit-tokens"),
                        requests_remaining=h.get("x-ratelimit-remaining-requests"),
                        tokens_remaining=h.get("x-ratelimit-remaining-tokens"),
                    )
                )
        except Exception as exc:
            report.checks.append(
                Check(
                    component,
                    "groq",
                    model,
                    "error",
                    f"listed, but smoke call failed: {_safe_error(exc)}",
                )
            )


def _verify_openai(
    settings: Settings, bundle: ProviderBundle, report: VerificationReport, client: OpenAI | None
):
    wanted: list[tuple[str, str]] = []
    if bundle.stt.name == "openai":
        wanted.append(("stt", settings.effective_stt_model))
    if bundle.tts.name == "openai":
        wanted.append(("tts", settings.tts_model))
    if not wanted:
        return
    try:
        available = _list_ids(client or build_openai_client(settings))
    except Exception as exc:
        for component, model in wanted:
            report.checks.append(Check(component, "openai", model, "error", _safe_error(exc)))
        return
    for component, model in wanted:
        if model in available:
            report.checks.append(Check(component, "openai", model, "ok", "listed by the API"))
        else:
            report.checks.append(
                Check(component, "openai", model, "missing", "not in OpenAI's current model list")
            )
    if bundle.tts.name == "openai" and settings.tts_voice not in OPENAI_TTS_VOICES:
        report.checks.append(
            Check("tts", "openai", f"voice:{settings.tts_voice}", "warning",
                  "voice not in the documented list; the API may reject it")
        )  # fmt: skip


def verify_models(
    settings: Settings,
    bundle: ProviderBundle,
    smoke: bool = True,
    *,
    groq_client: OpenAI | None = None,
    openai_client: OpenAI | None = None,
) -> VerificationReport:
    report = VerificationReport()
    _verify_groq(settings, bundle, smoke, report, groq_client)
    _verify_openai(settings, bundle, report, openai_client)
    if bundle.tts.client_side:
        report.checks.append(
            Check(
                "tts", "browser", bundle.tts_model, "skipped", "synthesised in the browser (free)"
            )
        )
    for component, provider in (("llm", bundle.llm), ("stt", bundle.stt), ("tts", bundle.tts)):
        if provider.is_mock:
            report.checks.append(
                Check(component, "mock", f"mock-{component}", "skipped", "mock provider")
            )
    log.info(
        "model_verification",
        extra={
            "passed": report.passed,
            "checks": [(c.component, c.model, c.status) for c in report.checks],
        },
    )
    return report


def ensure_verified(settings: Settings, bundle: ProviderBundle) -> VerificationReport:
    """Raise ModelVerificationError unless all configured models verified (cached 15 minutes)."""
    key = "|".join(
        [
            bundle.llm_model,
            bundle.simulator_model,
            bundle.judge_model,
            bundle.stt_model,
            bundle.tts_model,
        ]
    )
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1]
    report = verify_models(settings, bundle)
    if not report.passed:
        bad = "; ".join(f"{c.component} '{c.model}': {c.status}" for c in report.checks if not c.ok)
        raise ModelVerificationError(f"Model verification failed ({bad}).")
    _cache[key] = (time.monotonic(), report)
    return report


def clear_cache() -> None:
    _cache.clear()
