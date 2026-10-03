"""Conversation creation, listing and detail."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import analytics
from app.core.errors import NotFoundError
from app.db import repository
from app.db.session import get_db
from app.domain import ConversationSource, PromptVariant
from app.providers.factory import ProviderBundle, get_providers
from app.scenarios.loader import get_scenario, seed_scenarios
from app.schemas import ConversationCreate, ConversationDetail, ConversationList

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationDetail, status_code=201)
def create_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    providers: ProviderBundle = Depends(get_providers),
):
    if body.scenario_id is not None:
        if get_scenario(body.scenario_id) is None:
            raise NotFoundError("Scenario not found.")
        seed_scenarios(db)
    conversation = repository.create_conversation(
        db,
        variant=body.prompt_variant,
        source=ConversationSource.VOICE,
        run_mode=providers.run_mode,
        llm_model=providers.llm_model,
        scenario_id=body.scenario_id,
    )
    db.commit()
    detail = analytics.conversation_detail(db, conversation.id)
    assert detail is not None
    return detail


@router.get("", response_model=ConversationList)
def list_conversations(
    db: Session = Depends(get_db),
    prompt_variant: PromptVariant | None = None,
    scenario_id: str | None = None,
    category: str | None = None,
    goal_completed: bool | None = None,
    min_score: Annotated[float | None, Query(ge=0, le=5)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=5)] = None,
    run_mode: Literal["mock", "real"] | None = None,
    source: Literal["voice", "benchmark"] | None = None,
    benchmark_run_id: uuid.UUID | None = None,
    sort: Literal["recent", "score_asc", "score_desc"] = "recent",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return analytics.list_conversations(
        db,
        prompt_variant=prompt_variant.value if prompt_variant else None,
        scenario_id=scenario_id,
        category=category,
        goal_completed=goal_completed,
        min_score=min_score,
        max_score=max_score,
        run_mode=run_mode,
        source=source,
        benchmark_run_id=benchmark_run_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, db: Session = Depends(get_db)):
    detail = analytics.conversation_detail(db, conversation_id)
    if detail is None:
        raise NotFoundError("Conversation not found.")
    return detail
