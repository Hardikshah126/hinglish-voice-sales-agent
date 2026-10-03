"""Evaluation results and the aggregated dashboard summary."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import analytics
from app.db.session import get_db
from app.domain import PromptVariant
from app.schemas import EvaluationList, EvaluationSummary

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


@router.get("/summary", response_model=EvaluationSummary)
def summary(
    db: Session = Depends(get_db),
    run_id: uuid.UUID | None = None,
    run_mode: Literal["mock", "real"] | None = None,
):
    """Aggregate scores/latency for one benchmark run (default: latest, real before mock)."""
    return analytics.evaluation_summary(db, run_id=run_id, run_mode=run_mode)


@router.get("", response_model=EvaluationList)
def list_evaluations(
    db: Session = Depends(get_db),
    prompt_variant: PromptVariant | None = None,
    scenario_id: str | None = None,
    category: str | None = None,
    goal_completed: bool | None = None,
    min_score: Annotated[float | None, Query(ge=0, le=5)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=5)] = None,
    run_mode: Literal["mock", "real"] | None = None,
    benchmark_run_id: uuid.UUID | None = None,
    sort: Literal["recent", "score_asc", "score_desc"] = "recent",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return analytics.list_evaluations(
        db,
        prompt_variant=prompt_variant.value if prompt_variant else None,
        scenario_id=scenario_id,
        category=category,
        goal_completed=goal_completed,
        min_score=0.0 if min_score is None else min_score,
        max_score=max_score,
        run_mode=run_mode,
        source=None,
        benchmark_run_id=benchmark_run_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )
