"""Benchmark status and launch endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import analytics
from app.benchmark import runner
from app.config import Settings, get_settings
from app.db.models import BenchmarkRun
from app.db.session import get_db, get_sessionmaker
from app.domain import PromptVariant
from app.providers.factory import ProviderBundle, get_providers
from app.providers.model_check import ensure_verified
from app.scenarios.loader import get_scenario, load_scenarios
from app.schemas import BenchmarkRunRequest, BenchmarkRunStarted, BenchmarkStatus

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


@router.get("", response_model=BenchmarkStatus)
def benchmark_status(
    db: Session = Depends(get_db),
    providers: ProviderBundle = Depends(get_providers),
):
    runs = analytics.list_runs(db)
    return BenchmarkStatus(
        llm_provider=providers.llm.name,
        models=providers.llm_models,
        is_running=runner.is_running(),
        scenario_count=len(load_scenarios()),
        variants=[v.value for v in PromptVariant],
        latest_run=analytics.run_to_out(runs[0]) if runs else None,
        runs=[analytics.run_to_out(r) for r in runs],
    )


@router.post("/run", response_model=BenchmarkRunStarted, status_code=202)
def run_benchmark(
    body: BenchmarkRunRequest | None = None,
    db: Session = Depends(get_db),
    providers: ProviderBundle = Depends(get_providers),
    settings: Settings = Depends(get_settings),
):
    """Start a benchmark run in the background and return immediately (poll GET /api/benchmark)."""
    body = body or BenchmarkRunRequest()
    for sid in body.scenario_ids or []:
        if get_scenario(sid) is None:
            raise HTTPException(status_code=422, detail=f"Unknown scenario_id: {sid}")
    config = runner.BenchmarkConfig(
        variants=tuple(body.variants) if body.variants else tuple(PromptVariant),
        scenario_ids=tuple(body.scenario_ids) if body.scenario_ids else None,
        include_tts=(
            settings.benchmark_include_tts if body.include_tts is None else body.include_tts
        ),
        max_turns=body.max_turns or settings.benchmark_max_turns,
        concurrency=settings.benchmark_concurrency,
    )
    if not providers.llm.is_mock:  # never start a paid/quota-limited run on unverified models
        ensure_verified(settings, providers)
    run_id = runner.start_background(get_sessionmaker(), providers, settings, config)
    run = db.get(BenchmarkRun, run_id)
    assert run is not None
    return BenchmarkRunStarted(
        run_id=run.id,
        status=run.status,
        run_mode=run.run_mode,
        total_conversations=run.total_conversations,
    )
