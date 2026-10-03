"""Health, configuration, scenario listing and audio file serving."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.prompts.registry import PROMPT_REGISTRY
from app.providers.factory import ProviderBundle, get_providers
from app.scenarios.loader import load_scenarios
from app.schemas import ScenarioOut
from app.storage.audio import CONTENT_TYPES, AudioStorage, get_audio_storage

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        database = "unavailable"
    body = {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "llm_provider": "groq" if settings.llm_is_real else "mock",
        "environment": settings.app_env,
    }
    return JSONResponse(body, status_code=200 if database == "ok" else 503)


@router.get("/api/config")
def app_config(
    providers: ProviderBundle = Depends(get_providers),
    settings: Settings = Depends(get_settings),
):
    return {
        "components": providers.components,
        "mock_components": providers.mock_components,
        "is_mock": bool(providers.mock_components),
        "llm_is_mock": providers.llm.is_mock,
        "prompt_variants": [
            {"id": spec.variant.value, "title": spec.title, "description": spec.description}
            for spec in PROMPT_REGISTRY.values()
        ],
        "limits": {"max_audio_bytes": settings.max_audio_bytes},
        "benchmark": {"max_turns": settings.benchmark_max_turns},
    }


@router.get("/api/scenarios", response_model=list[ScenarioOut])
def scenarios():
    return [ScenarioOut(**s.model_dump()) for s in load_scenarios()]


@router.get("/api/audio/{key}")
def get_audio(key: str, storage: AudioStorage = Depends(get_audio_storage)):
    path = storage.local_path(key)
    if path is None:
        raise NotFoundError("Audio not found.")
    return FileResponse(path, media_type=CONTENT_TYPES[path.suffix.lstrip(".")])
