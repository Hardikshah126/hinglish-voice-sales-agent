"""Groq LLM provider (OpenAI-compatible chat completions API).

Latency honesty: retries are done here, not inside the SDK, so the reported latency is the
duration of the *successful request only*. Time spent waiting out a rate limit is logged
but never counted as model latency.
"""

import re
import time
from collections.abc import Callable

import openai
from openai import OpenAI

from app.config import Settings
from app.core.errors import (
    LLMError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    ProviderConfigError,
)
from app.core.logging import get_logger
from app.providers.base import LLMProvider, LLMRequest, LLMResponse

log = get_logger(__name__)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
_BACKOFF_S = (1.0, 2.0, 4.0, 8.0)


def build_groq_client(settings: Settings) -> OpenAI:
    if not settings.has_groq_key or settings.groq_api_key is None:
        raise ProviderConfigError("GROQ_API_KEY is not set.")
    # max_retries=0: retries are handled (and timed) by GroqLLMProvider.
    return OpenAI(
        api_key=settings.groq_api_key.get_secret_value(),
        base_url=settings.groq_base_url,
        timeout=settings.llm_timeout_s,
        max_retries=0,
    )


def is_gpt_oss(model: str) -> bool:
    return model.startswith("openai/gpt-oss")


def reasoning_kwargs(model: str, effort: str | None, default_effort: str) -> dict:
    """Model-family specific reasoning controls (see docs/model-verification.md).

    gpt-oss always reasons (low/medium/high). Qwen3.8 can run with thinking off ("none"),
    which is what the conversational agent and simulator want for latency.
    """
    if is_gpt_oss(model):
        return {
            "reasoning_effort": effort or default_effort,
            "extra_body": {"include_reasoning": False},
        }
    if model.startswith("qwen/"):
        return {
            "reasoning_effort": effort or "none",
            "extra_body": {"reasoning_format": "hidden"},
        }
    return {}


def _retry_after(exc: openai.APIStatusError) -> float | None:
    raw = exc.response.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


class GroqLLMProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        client: OpenAI,
        settings: Settings,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._client = client
        self._settings = settings
        self._sleep = sleep

    def build_kwargs(self, request: LLMRequest, model: str) -> dict:
        s = self._settings
        default_tokens = (
            s.judge_max_output_tokens if request.task == "judge" else s.llm_max_output_tokens
        )
        budget = request.max_output_tokens or default_tokens
        if is_gpt_oss(model) and request.max_output_tokens:
            budget += s.reasoning_token_allowance  # visible budget + room for reasoning tokens
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system},
                *[{"role": m.role, "content": m.content} for m in request.messages],
            ],
            "max_completion_tokens": budget,
            "timeout": request.timeout_s
            or (s.judge_timeout_s if request.task == "judge" else s.llm_timeout_s),
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.seed is not None:
            kwargs["seed"] = request.seed
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        kwargs.update(reasoning_kwargs(model, request.reasoning_effort, s.reasoning_effort))
        return kwargs

    def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._settings.llm_model
        kwargs = self.build_kwargs(request, model)
        attempts = self._settings.llm_max_retries + 1

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                completion = self._client.chat.completions.create(**kwargs)
            except openai.APITimeoutError as exc:
                raise LLMTimeoutError() from exc
            except openai.RateLimitError as exc:
                wait = _retry_after(exc)
                if wait is not None and wait > self._settings.max_retry_wait_s:
                    log.warning(
                        "llm_quota_exhausted",
                        extra={"model": model, "task": request.task, "retry_after_s": wait},
                    )
                    raise LLMQuotaExhaustedError(
                        f"Groq quota for model '{model}' is exhausted; it resets in about "
                        f"{int(wait // 60)} min. Resume later."
                    ) from exc
                if attempt == attempts:
                    raise LLMRateLimitError() from exc
                self._backoff(attempt, wait, model, request.task, "rate_limited")
                continue
            except (openai.InternalServerError, openai.APIConnectionError) as exc:
                if attempt == attempts:
                    raise LLMError() from exc
                self._backoff(attempt, None, model, request.task, type(exc).__name__)
                continue
            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                raise ProviderConfigError("Groq rejected the configured API key.") from exc
            except openai.NotFoundError as exc:
                raise ProviderConfigError(
                    f"Model '{model}' is not available on Groq. Run `python -m app.cli verify-models`."
                ) from exc
            except openai.BadRequestError as exc:
                log.error(
                    "groq_bad_request",
                    extra={"model": model, "task": request.task, "error_code": exc.code},
                )
                if exc.code == "json_validate_failed":
                    raise LLMResponseError() from exc  # callers retry malformed JSON once
                raise LLMError() from exc
            except openai.APIError as exc:
                log.error("groq_error", extra={"model": model, "error_type": type(exc).__name__})
                raise LLMError() from exc
            latency_ms = (time.perf_counter() - started) * 1000

            choice = completion.choices[0] if completion.choices else None
            text = _THINK_BLOCK.sub("", (choice.message.content or "") if choice else "").strip()
            if not text:
                log.warning(
                    "llm_empty_response",
                    extra={
                        "model": model,
                        "task": request.task,
                        "finish_reason": choice.finish_reason if choice else None,
                    },
                )
                raise LLMResponseError("The language model returned an empty response.")
            return LLMResponse(text=text, latency_ms=latency_ms, model=model)

        raise LLMError()  # unreachable: the loop always returns or raises

    def _backoff(self, attempt: int, retry_after: float | None, model: str, task: str, why: str):
        wait = retry_after if retry_after is not None else _BACKOFF_S[min(attempt - 1, 3)]
        wait = min(wait, self._settings.max_retry_wait_s)
        log.info(
            "llm_retry",
            extra={"model": model, "task": task, "attempt": attempt, "wait_s": wait, "reason": why},
        )
        self._sleep(wait)
