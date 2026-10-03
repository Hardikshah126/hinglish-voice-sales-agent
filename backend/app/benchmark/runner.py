"""Benchmark runner: every scenario x every prompt strategy, with a shared simulator + judge.

Design notes
- The customer simulator, judge, seed, temperatures and turn limit are identical for all
  strategies. The ONLY thing that changes between the paired conversations is the agent's
  system prompt.
- Each conversation is persisted in one transaction after it has been fully simulated and
  evaluated, so the database never contains half-finished benchmark conversations.
- Benchmark latency is *simulated-benchmark* latency: customer input is text (no STT),
  and each agent turn measures LLM (+ TTS when enabled) wall time with a monotonic clock.
"""

import threading
import time
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.agent.sales_agent import ConversationState, SalesAgent
from app.agent.simulator import CustomerSimulator
from app.config import Settings
from app.core.errors import AppError, ConflictError, LLMQuotaExhaustedError
from app.core.logging import get_logger
from app.db import repository
from app.db.models import BenchmarkRun, Conversation
from app.domain import ConversationSource, PromptVariant, RunStatus, StopReason
from app.evaluation.evaluator import ConversationEvaluator
from app.providers.factory import ProviderBundle
from app.scenarios.loader import ScenarioSpec, load_scenarios, seed_scenarios

log = get_logger(__name__)

_run_lock = threading.Lock()
_active_run_id: uuid.UUID | None = None


@dataclass(frozen=True)
class BenchmarkConfig:
    variants: tuple[PromptVariant, ...] = tuple(PromptVariant)
    scenario_ids: tuple[str, ...] | None = None  # None = all scenarios
    include_tts: bool = True
    max_turns: int = 8
    concurrency: int = 1

    def to_json(self) -> dict:
        return {
            "variants": [v.value for v in self.variants],
            "scenario_ids": list(self.scenario_ids) if self.scenario_ids else None,
            "include_tts": self.include_tts,
            "max_turns": self.max_turns,
            "concurrency": self.concurrency,
        }

    @classmethod
    def from_json(cls, data: dict) -> "BenchmarkConfig":
        return cls(
            variants=tuple(PromptVariant(v) for v in data["variants"]),
            scenario_ids=tuple(data["scenario_ids"]) if data.get("scenario_ids") else None,
            include_tts=data["include_tts"],
            max_turns=data["max_turns"],
            concurrency=data.get("concurrency", 1),
        )


def select_scenarios(config: BenchmarkConfig) -> list[ScenarioSpec]:
    scenarios = list(load_scenarios())
    if config.scenario_ids:
        wanted = set(config.scenario_ids)
        scenarios = [s for s in scenarios if s.id in wanted]
    return scenarios


def run_conversation(
    session_factory: sessionmaker[Session],
    providers: ProviderBundle,
    settings: Settings,
    scenario: ScenarioSpec,
    variant: PromptVariant,
    run_id: uuid.UUID,
    config: BenchmarkConfig,
) -> uuid.UUID:
    """Simulate, evaluate and persist one scenario/variant conversation."""
    agent = SalesAgent(providers.llm, variant, settings)
    simulator = CustomerSimulator(providers.llm, settings)
    evaluator = ConversationEvaluator(providers.llm, settings, providers.judge_model)
    state = ConversationState()
    tts_timed = config.include_tts and providers.times_tts_in_benchmarks

    exchanges: list[tuple[int, str, str, float, float | None, float]] = []
    customer_text = scenario.initial_message
    stop_reason = StopReason.MAX_TURNS
    pending_stop: StopReason | None = None

    for turn in range(1, config.max_turns + 1):
        started = time.perf_counter()
        reply = agent.respond(state, customer_text)
        tts_ms: float | None = None
        if tts_timed:
            tts_ms = providers.tts.synthesize(reply.text).latency_ms  # audio is discarded
        total_ms = (time.perf_counter() - started) * 1000
        exchanges.append((turn, customer_text, reply.text, reply.llm_latency_ms, tts_ms, total_ms))
        log.info(
            "benchmark_turn",
            extra={
                "benchmark_run_id": str(run_id),
                "scenario_id": scenario.id,
                "prompt_variant": variant.value,
                "turn_number": turn,
                "stt_ms": None,
                "llm_ms": round(reply.llm_latency_ms, 1),
                "tts_ms": None if tts_ms is None else round(tts_ms, 1),
                "total_ms": round(total_ms, 1),
            },
        )
        if pending_stop is not None:
            stop_reason = pending_stop
            break
        if turn == config.max_turns:
            break
        simulated = simulator.next_message(scenario, state)
        customer_text = simulated.message
        if simulated.goal_reached:
            pending_stop = StopReason.GOAL_REACHED
        elif simulated.wants_to_end:
            pending_stop = StopReason.CUSTOMER_LEFT

    result = evaluator.evaluate(scenario, state)

    with session_factory() as db:
        conversation = repository.create_conversation(
            db,
            variant=variant,
            source=ConversationSource.BENCHMARK,
            run_mode=providers.run_mode,
            llm_model=providers.llm_model,
            scenario_id=scenario.id,
            benchmark_run_id=run_id,
        )
        for turn, cust, agent_text, llm_ms, tts_ms, total_ms in exchanges:
            repository.add_exchange(
                db,
                conversation,
                turn_number=turn,
                customer_text=cust,
                agent_text=agent_text,
                source=ConversationSource.BENCHMARK,
                stt_ms=None,
                llm_ms=llm_ms,
                tts_ms=tts_ms,
                total_ms=total_ms,
            )
        conversation.stop_reason = stop_reason.value
        repository.save_evaluation(db, conversation, result, datetime.now().astimezone())
        db.commit()
        return conversation.id


def create_run(
    session_factory: sessionmaker[Session],
    providers: ProviderBundle,
    config: BenchmarkConfig,
) -> uuid.UUID:
    scenarios = select_scenarios(config)
    if not scenarios:
        raise ValueError("No scenarios selected.")
    with session_factory() as db:
        seed_scenarios(db)
        run = BenchmarkRun(
            id=uuid.uuid4(),
            status=RunStatus.RUNNING.value,
            run_mode=providers.run_mode.value,
            config={**config.to_json(), "models": providers.llm_models},
            total_conversations=len(scenarios) * len(config.variants),
        )
        db.add(run)
        db.commit()
        return run.id


def execute_run(
    session_factory: sessionmaker[Session],
    providers: ProviderBundle,
    settings: Settings,
    run_id: uuid.UUID,
) -> RunStatus:
    """Run (or resume) every not-yet-completed cell of a benchmark run."""
    with session_factory() as db:
        run = db.get(BenchmarkRun, run_id)
        if run is None:
            raise ValueError(f"Benchmark run {run_id} not found")
        config = BenchmarkConfig.from_json(run.config)
        recorded = run.config.get("models")
        if recorded and recorded != providers.llm_models:
            raise ValueError(
                "The configured models differ from the ones this run started with "
                f"({recorded}); mixing models would break the controlled comparison."
            )
        run.failed_conversations = 0  # cells that failed earlier are retried on resume
        done = set(
            db.execute(
                select(Conversation.scenario_id, Conversation.prompt_variant).where(
                    Conversation.benchmark_run_id == run_id
                )
            ).all()
        )
        run.status = RunStatus.RUNNING.value
        run.completed_at = None
        db.commit()

    # Interleave variants per scenario so a cut-short run still has paired comparisons.
    cells = [
        (scenario, variant)
        for scenario in select_scenarios(config)
        for variant in config.variants
        if (scenario.id, variant.value) not in done
    ]
    log.info("benchmark_started", extra={"benchmark_run_id": str(run_id), "cells": len(cells)})

    quota_hit = threading.Event()

    def work(cell: tuple[ScenarioSpec, PromptVariant]) -> None:
        scenario, variant = cell
        if quota_hit.is_set():
            return  # provider quota exhausted: leave remaining cells for `--resume`
        try:
            run_conversation(
                session_factory, providers, settings, scenario, variant, run_id, config
            )
            outcome, error = "completed_conversations", None
        except LLMQuotaExhaustedError as exc:
            quota_hit.set()
            log.warning("benchmark_quota_exhausted", extra={"benchmark_run_id": str(run_id)})
            with session_factory() as db:
                db.execute(
                    update(BenchmarkRun)
                    .where(BenchmarkRun.id == run_id)
                    .values(error=f"Stopped: {exc.message}"[:500])
                )
                db.commit()
            return
        except Exception as exc:
            log.error(
                "benchmark_conversation_failed",
                extra={
                    "benchmark_run_id": str(run_id),
                    "scenario_id": scenario.id,
                    "prompt_variant": variant.value,
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            outcome = "failed_conversations"
            error = exc.message if isinstance(exc, AppError) else type(exc).__name__
        with session_factory() as db:
            column = getattr(BenchmarkRun, outcome)
            values = {outcome: column + 1}
            if error:
                values["error"] = f"{scenario.id}/{variant.value}: {error}"[:500]
            db.execute(update(BenchmarkRun).where(BenchmarkRun.id == run_id).values(**values))
            db.commit()

    with ThreadPoolExecutor(max_workers=max(1, config.concurrency)) as pool:
        list(pool.map(work, cells))

    with session_factory() as db:
        run = db.get(BenchmarkRun, run_id)
        assert run is not None
        total_done = db.scalar(
            select(BenchmarkRun.completed_conversations).where(BenchmarkRun.id == run_id)
        )
        if total_done == run.total_conversations:
            status = RunStatus.COMPLETED
        elif total_done:
            status = RunStatus.PARTIAL
        else:
            status = RunStatus.FAILED
        run.status = status.value
        run.completed_at = datetime.now().astimezone()
        db.commit()
    log.info("benchmark_finished", extra={"benchmark_run_id": str(run_id), "status": status.value})
    return status


def start_background(
    session_factory: sessionmaker[Session],
    providers: ProviderBundle,
    settings: Settings,
    config: BenchmarkConfig,
) -> uuid.UUID:
    """Create a run and execute it on a daemon thread. Only one run at a time."""
    global _active_run_id
    with _run_lock:
        if _active_run_id is not None:
            raise ConflictError("A benchmark run is already in progress.")
        run_id = create_run(session_factory, providers, config)
        _active_run_id = run_id

    def target() -> None:
        global _active_run_id
        try:
            execute_run(session_factory, providers, settings, run_id)
        except Exception:
            log.error("benchmark_crashed", extra={"benchmark_run_id": str(run_id)}, exc_info=True)
            with session_factory() as db:
                db.execute(
                    update(BenchmarkRun)
                    .where(BenchmarkRun.id == run_id)
                    .values(status=RunStatus.FAILED.value, error="Benchmark crashed unexpectedly.")
                )
                db.commit()
        finally:
            with _run_lock:
                _active_run_id = None

    threading.Thread(target=target, name=f"benchmark-{run_id}", daemon=True).start()
    return run_id


def is_running() -> bool:
    return _active_run_id is not None


def mark_interrupted_runs(session_factory: sessionmaker[Session]) -> int:
    """Runs left 'running' by a previous process can never finish; mark them failed."""
    with session_factory() as db:
        stuck = db.scalars(
            select(BenchmarkRun).where(BenchmarkRun.status == RunStatus.RUNNING.value)
        ).all()
        for run in stuck:
            run.status = RunStatus.FAILED.value
            run.error = "Interrupted by server restart."
        db.commit()
        return len(stuck)


def filter_variants(names: Sequence[str] | None) -> tuple[PromptVariant, ...]:
    return tuple(PromptVariant(n) for n in names) if names else tuple(PromptVariant)
