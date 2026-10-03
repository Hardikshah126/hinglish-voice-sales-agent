"""POST /api/voice/respond: one spoken turn in, one spoken reply out."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.domain import PromptVariant
from app.providers.factory import ProviderBundle, get_providers
from app.schemas import LatencyOut, VoiceRespondResponse
from app.storage.audio import AudioStorage, get_audio_storage
from app.voice.pipeline import run_voice_turn

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/respond", response_model=VoiceRespondResponse)
def respond(
    audio: Annotated[UploadFile, File(description="Recorded speech (webm, wav, mp3, m4a, ogg)")],
    prompt_variant: Annotated[PromptVariant, Form()],
    conversation_id: Annotated[uuid.UUID | None, Form()] = None,
    transcript_override: Annotated[
        str | None,
        Form(max_length=500, description="Mock-STT only: use this text instead of transcribing."),
    ] = None,
    db: Session = Depends(get_db),
    providers: ProviderBundle = Depends(get_providers),
    storage: AudioStorage = Depends(get_audio_storage),
    settings: Settings = Depends(get_settings),
):
    # Read at most max+1 bytes so an oversized upload is rejected without buffering it all.
    data = audio.file.read(settings.max_audio_bytes + 1)
    result = run_voice_turn(
        db,
        providers,
        storage,
        settings,
        audio=data,
        content_type=audio.content_type,
        variant=prompt_variant,
        conversation_id=conversation_id,
        transcript_override=transcript_override,
    )
    return VoiceRespondResponse(
        conversation_id=result.conversation_id,
        transcript=result.transcript,
        response_text=result.response_text,
        audio_url=result.audio_url,
        latency=LatencyOut(
            stt_ms=result.latency.stt_ms,
            llm_ms=result.latency.llm_ms,
            tts_ms=result.latency.tts_ms,
            total_ms=result.latency.total_ms,
        ),
        warnings=result.warnings,
        mock_mode=bool(result.mock_components),
        mock_components=result.mock_components,
        speak_client_side=result.speak_client_side,
    )
