"""Real-time voice turn: audio -> STT -> conversation state -> prompt strategy -> LLM -> TTS."""

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agent.sales_agent import SalesAgent
from app.config import Settings
from app.core.errors import ConflictError, InvalidAudioError, NotFoundError, TTSError
from app.core.logging import get_logger
from app.db import repository
from app.db.models import Conversation
from app.domain import ConversationSource, PromptVariant
from app.providers.base import STTResult
from app.providers.factory import ProviderBundle
from app.storage.audio import AudioStorage
from app.voice.audio_validation import validate_audio

log = get_logger(__name__)


@dataclass
class LatencyBreakdown:
    stt_ms: float
    llm_ms: float
    tts_ms: float | None
    total_ms: float


@dataclass
class VoiceTurnResult:
    conversation_id: uuid.UUID
    transcript: str
    response_text: str
    audio_url: str | None
    latency: LatencyBreakdown
    warnings: list[str] = field(default_factory=list)
    mock_components: list[str] = field(default_factory=list)
    speak_client_side: bool = False


def _get_or_create_conversation(
    db: Session,
    providers: ProviderBundle,
    conversation_id: uuid.UUID | None,
    variant: PromptVariant,
) -> Conversation:
    if conversation_id is None:
        return repository.create_conversation(
            db,
            variant=variant,
            source=ConversationSource.VOICE,
            run_mode=providers.voice_run_mode,
            llm_model=providers.llm_model,
        )
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    if conversation.source != ConversationSource.VOICE.value:
        raise ConflictError("Only live voice conversations accept new voice turns.")
    if conversation.prompt_variant != variant.value:
        raise ConflictError("Prompt strategy cannot change within a conversation.")
    return conversation


def run_voice_turn(
    db: Session,
    providers: ProviderBundle,
    storage: AudioStorage,
    settings: Settings,
    *,
    audio: bytes,
    content_type: str | None,
    variant: PromptVariant,
    conversation_id: uuid.UUID | None = None,
    transcript_override: str | None = None,
) -> VoiceTurnResult:
    validated = validate_audio(audio, content_type, settings.max_audio_bytes)
    conversation = _get_or_create_conversation(db, providers, conversation_id, variant)
    state = repository.load_state(conversation)
    turn_number = repository.next_turn_number(db, conversation.id)
    ctx = {
        "conversation_id": str(conversation.id),
        "prompt_variant": variant.value,
        "turn_number": turn_number,
    }

    warnings: list[str] = []
    pipeline_start = time.perf_counter()

    # 1. Speech-to-text. The transcript override only exists so the mock stack can be
    #    demoed without a microphone or API key; it is ignored by real providers.
    if transcript_override and providers.stt.is_mock:
        stt = STTResult(text=transcript_override.strip(), latency_ms=0.0, model="mock-override")
    else:
        stt = providers.stt.transcribe(audio, validated.filename, validated.content_type)
    if not stt.text.strip():
        raise InvalidAudioError("No speech was detected in the audio.")

    # 2. Prompt strategy + LLM, with the full conversation history.
    agent = SalesAgent(providers.llm, variant, settings)
    reply = agent.respond(state, stt.text)

    # 3. Text-to-speech. A TTS failure degrades gracefully to a text-only reply.
    audio_url: str | None = None
    tts_ms: float | None = None
    if not providers.tts.client_side:  # client-side TTS is spoken by the browser, not timed here
        try:
            tts = providers.tts.synthesize(reply.text)
            tts_ms = tts.latency_ms
            audio_url = storage.url_for(storage.save(tts.audio, tts.extension))
        except TTSError:
            warnings.append("tts_failed")
            log.warning("tts_failed_text_only_fallback", extra=ctx)

    total_ms = (time.perf_counter() - pipeline_start) * 1000

    repository.add_exchange(
        db,
        conversation,
        turn_number=turn_number,
        customer_text=stt.text,
        agent_text=reply.text,
        source=ConversationSource.VOICE,
        stt_ms=stt.latency_ms,
        llm_ms=reply.llm_latency_ms,
        tts_ms=tts_ms,
        total_ms=total_ms,
    )
    db.commit()

    log.info(
        "voice_turn_completed",
        extra={
            **ctx,
            "stt_ms": round(stt.latency_ms, 1),
            "llm_ms": round(reply.llm_latency_ms, 1),
            "tts_ms": None if tts_ms is None else round(tts_ms, 1),
            "total_ms": round(total_ms, 1),
            "run_mode": providers.voice_run_mode.value,
            "mock_components": providers.mock_components,
        },
    )
    return VoiceTurnResult(
        conversation_id=conversation.id,
        transcript=stt.text,
        response_text=reply.text,
        audio_url=audio_url,
        latency=LatencyBreakdown(stt.latency_ms, reply.llm_latency_ms, tts_ms, total_ms),
        warnings=warnings,
        mock_components=providers.mock_components,
        speak_client_side=providers.tts.client_side,
    )
