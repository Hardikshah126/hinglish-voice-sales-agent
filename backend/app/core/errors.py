"""Typed application errors. API handlers turn these into safe JSON responses."""


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    default_message = "Something went wrong."

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)


class InvalidAudioError(AppError):
    status_code = 422
    code = "invalid_audio"
    default_message = "The uploaded audio is empty or corrupted."


class UnsupportedAudioError(AppError):
    status_code = 415
    code = "unsupported_audio_format"
    default_message = "Unsupported audio format. Use webm, wav, mp3, mp4/m4a or ogg."


class AudioTooLargeError(AppError):
    status_code = 413
    code = "audio_too_large"
    default_message = "The uploaded audio exceeds the maximum allowed size."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "Resource not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    default_message = "Request conflicts with the current state."


class STTError(AppError):
    status_code = 502
    code = "stt_failed"
    default_message = "Speech-to-text failed. Please try again."


class LLMError(AppError):
    status_code = 502
    code = "llm_failed"
    default_message = "The language model request failed. Please try again."


class LLMTimeoutError(LLMError):
    status_code = 504
    code = "llm_timeout"
    default_message = "The language model timed out. Please try again."


class LLMRateLimitError(LLMError):
    status_code = 429
    code = "llm_rate_limited"
    default_message = "The language model is rate limited right now. Please retry shortly."


class LLMQuotaExhaustedError(LLMRateLimitError):
    """The provider's per-day (or otherwise long-window) quota is used up."""

    code = "llm_quota_exhausted"
    default_message = "The language model quota is exhausted. Try again after it resets."


class LLMResponseError(LLMError):
    code = "llm_malformed_response"
    default_message = "The language model returned a response that could not be parsed."


class TTSError(AppError):
    status_code = 502
    code = "tts_failed"
    default_message = "Text-to-speech failed."


class ProviderConfigError(AppError):
    status_code = 503
    code = "provider_not_configured"
    default_message = "The AI provider is not configured on the server."
