"""Read-side queries for the dashboard, conversation explorer and benchmark report.

The standalone, annotated versions of the aggregate queries live in sql/analysis.sql.
"""

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import BenchmarkRun, Conversation, Scenario
from app.domain import RunMode
from app.schemas import (
    BenchmarkRunOut,
    ConversationDetail,
    ConversationFlag,
    ConversationList,
    ConversationListItem,
    EvaluationList,
    EvaluationListItem,
    EvaluationOut,
    EvaluationSummary,
    GroupedScore,
    LatencyOut,
    LatencyStats,
    MatrixCell,
    ScenarioOut,
    ScenarioRow,
    ScoreDistribution,
    TurnOut,
    VariantSummary,
)

LATENCY_NOTE = (
    "Benchmark latency is measured per agent turn with a monotonic clock, but customer input "
    "is text (no speech-to-text) and conversations run server-side. It is simulated-benchmark "
    "latency, not real end-to-end voice latency."
)

VARIANT_ORDER = ("zero_shot", "few_shot", "persona")


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def run_to_out(run: BenchmarkRun) -> BenchmarkRunOut:
    return BenchmarkRunOut(
        id=run.id,
        status=run.status,
        run_mode=run.run_mode,
        total_conversations=run.total_conversations,
        completed_conversations=run.completed_conversations,
        failed_conversations=run.failed_conversations,
        error=run.error,
        started_at=run.started_at,
        completed_at=run.completed_at,
        config=run.config,
    )


def list_runs(db: Session, limit: int = 10) -> list[BenchmarkRun]:
    return list(
        db.scalars(select(BenchmarkRun).order_by(BenchmarkRun.started_at.desc()).limit(limit))
    )


def resolve_run(
    db: Session, run_id: uuid.UUID | None = None, run_mode: str | None = None
) -> BenchmarkRun | None:
    """The run the dashboard should show: explicit id, else latest with data (real first)."""
    if run_id is not None:
        return db.get(BenchmarkRun, run_id)
    modes = [run_mode] if run_mode else [RunMode.REAL.value, RunMode.MOCK.value]
    for mode in modes:
        run = db.scalars(
            select(BenchmarkRun)
            .where(BenchmarkRun.run_mode == mode, BenchmarkRun.completed_conversations > 0)
            .order_by(BenchmarkRun.started_at.desc())
            .limit(1)
        ).first()
        if run is not None:
            return run
    return None


def available_modes(db: Session) -> list[str]:
    rows = db.execute(
        text(
            "SELECT DISTINCT run_mode FROM benchmark_runs "
            "WHERE completed_conversations > 0 ORDER BY run_mode"
        )
    )
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------- summary
def evaluation_summary(
    db: Session, run_id: uuid.UUID | None = None, run_mode: str | None = None
) -> EvaluationSummary:
    run = resolve_run(db, run_id, run_mode)
    modes = available_modes(db)
    if run is None:
        return EvaluationSummary(
            benchmark_run=None,
            run_mode=run_mode,
            is_mock=run_mode == RunMode.MOCK.value,
            available_modes=modes,
            conversations=0,
            scenarios=0,
            prompt_variants=0,
            by_variant=[],
            by_category=[],
            by_difficulty=[],
            scenario_matrix=[],
            distributions=[],
            failure_cases=[],
            high_latency=[],
            latency_note=LATENCY_NOTE,
        )
    p = {"run": run.id}

    by_variant = _variant_summaries(db, p)
    totals = db.execute(
        text(
            "SELECT count(*), count(DISTINCT scenario_id), count(DISTINCT prompt_variant) "
            "FROM conversation_results WHERE benchmark_run_id = :run"
        ),
        p,
    ).one()

    return EvaluationSummary(
        benchmark_run=run_to_out(run),
        run_mode=run.run_mode,
        is_mock=run.run_mode == RunMode.MOCK.value,
        available_modes=modes,
        conversations=totals[0],
        scenarios=totals[1],
        prompt_variants=totals[2],
        by_variant=by_variant,
        by_category=_grouped(db, p, "category"),
        by_difficulty=_grouped(db, p, "difficulty"),
        scenario_matrix=_scenario_matrix(db, p),
        distributions=_distributions(db, p),
        failure_cases=_flags(
            db, p, "goal_completion_score = 0 OR overall_score < 2.5", "overall_score ASC", 10
        ),
        high_latency=_flags(
            db, p, "avg_total_latency_ms IS NOT NULL", "avg_total_latency_ms DESC", 10
        ),
        latency_note=LATENCY_NOTE,
    )


def _variant_summaries(db: Session, p: dict) -> list[VariantSummary]:
    quality = db.execute(
        text("""
            SELECT prompt_variant,
                   count(*)                                         AS n,
                   avg((goal_completion_score = 2)::int)            AS goal_rate,
                   avg(goal_completion_score)                       AS avg_goal,
                   avg(objection_handling_score)                    AS avg_obj,
                   count(objection_handling_score)                  AS obj_n,
                   avg(conversation_quality_score)                  AS avg_quality,
                   avg(overall_score)                               AS avg_overall,
                   sum((goal_completion_score = 2)::int)            AS goals,
                   sum(invented_claims::int)                        AS invented
            FROM conversation_results
            WHERE benchmark_run_id = :run
            GROUP BY prompt_variant
            """),
        p,
    ).mappings()
    latency = {
        r["prompt_variant"]: r
        for r in db.execute(
            text("""
                SELECT prompt_variant,
                       count(*)                                                   AS samples,
                       avg(total_latency_ms)                                      AS avg_total,
                       percentile_cont(0.5)  WITHIN GROUP (ORDER BY total_latency_ms) AS p50,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95,
                       avg(llm_latency_ms)  AS avg_llm,
                       avg(tts_latency_ms)  AS avg_tts,
                       avg(stt_latency_ms)  AS avg_stt
                FROM turn_latencies
                WHERE benchmark_run_id = :run
                GROUP BY prompt_variant
                """),
            p,
        ).mappings()
    }
    out = []
    for r in quality:
        lat = latency.get(r["prompt_variant"])
        out.append(
            VariantSummary(
                prompt_variant=r["prompt_variant"],
                conversations=r["n"],
                goal_completion_rate=float(r["goal_rate"]),
                avg_goal_score=float(r["avg_goal"]),
                avg_objection_score=_f(r["avg_obj"]),
                objection_samples=r["obj_n"],
                avg_quality_score=float(r["avg_quality"]),
                avg_overall_score=float(r["avg_overall"]),
                completed_goals=int(r["goals"]),
                invented_claims_count=int(r["invented"] or 0),
                latency=LatencyStats(
                    avg_total_ms=_f(lat["avg_total"]) if lat else None,
                    p50_total_ms=_f(lat["p50"]) if lat else None,
                    p95_total_ms=_f(lat["p95"]) if lat else None,
                    avg_llm_ms=_f(lat["avg_llm"]) if lat else None,
                    avg_tts_ms=_f(lat["avg_tts"]) if lat else None,
                    avg_stt_ms=_f(lat["avg_stt"]) if lat else None,
                    samples=lat["samples"] if lat else 0,
                ),
            )
        )
    return sorted(out, key=lambda v: VARIANT_ORDER.index(v.prompt_variant))


def _grouped(db: Session, p: dict, column: str) -> list[GroupedScore]:
    assert column in {"category", "difficulty"}  # column is interpolated: whitelist only
    rows = db.execute(
        text(f"""
            SELECT {column}::text AS grp, prompt_variant, count(*) AS n,
                   avg(overall_score) AS avg_overall,
                   avg((goal_completion_score = 2)::int) AS goal_rate
            FROM conversation_results
            WHERE benchmark_run_id = :run
            GROUP BY {column}, prompt_variant
            ORDER BY {column}, prompt_variant
            """),
        p,
    ).mappings()
    return [
        GroupedScore(
            group=r["grp"],
            prompt_variant=r["prompt_variant"],
            conversations=r["n"],
            avg_overall_score=float(r["avg_overall"]),
            goal_completion_rate=float(r["goal_rate"]),
        )
        for r in rows
    ]


def _scenario_matrix(db: Session, p: dict) -> list[ScenarioRow]:
    rows = db.execute(
        text("""
            SELECT scenario_id, scenario_name, category, difficulty, prompt_variant,
                   overall_score, goal_completion_score, objection_handling_score,
                   conversation_quality_score, conversation_id
            FROM conversation_results
            WHERE benchmark_run_id = :run AND scenario_id IS NOT NULL
            ORDER BY category, difficulty, scenario_id
            """),
        p,
    ).mappings()
    matrix: dict[str, ScenarioRow] = {}
    for r in rows:
        row = matrix.setdefault(
            r["scenario_id"],
            ScenarioRow(
                scenario_id=r["scenario_id"],
                scenario_name=r["scenario_name"],
                category=r["category"],
                difficulty=r["difficulty"],
                cells=[],
            ),
        )
        row.cells.append(
            MatrixCell(
                prompt_variant=r["prompt_variant"],
                overall_score=float(r["overall_score"]),
                goal_completion_score=r["goal_completion_score"],
                objection_handling_score=r["objection_handling_score"],
                conversation_quality_score=r["conversation_quality_score"],
                conversation_id=r["conversation_id"],
            )
        )
    for row in matrix.values():
        row.cells.sort(key=lambda c: VARIANT_ORDER.index(c.prompt_variant))
    return list(matrix.values())


def _distributions(db: Session, p: dict) -> list[ScoreDistribution]:
    out: list[ScoreDistribution] = []
    for metric, column in (
        ("goal", "goal_completion_score"),
        ("objection", "objection_handling_score"),
        ("quality", "conversation_quality_score"),
    ):
        rows = db.execute(
            text(f"""
                SELECT prompt_variant, {column} AS score, count(*) AS n
                FROM conversation_results
                WHERE benchmark_run_id = :run AND {column} IS NOT NULL
                GROUP BY prompt_variant, {column}
                ORDER BY prompt_variant, {column}
                """),
            p,
        )
        out.extend(
            ScoreDistribution(metric=metric, prompt_variant=r[0], score=r[1], count=r[2])  # type: ignore[arg-type]
            for r in rows
        )
    return out


def _flags(db: Session, p: dict, where: str, order: str, limit: int) -> list[ConversationFlag]:
    # `where` / `order` are trusted constants from this module, never user input.
    rows = db.execute(
        text(f"""
            SELECT conversation_id, prompt_variant, scenario_id, scenario_name,
                   overall_score, goal_completion_score, avg_total_latency_ms
            FROM conversation_results
            WHERE benchmark_run_id = :run AND ({where})
            ORDER BY {order}
            LIMIT {int(limit)}
            """),
        p,
    ).mappings()
    return [
        ConversationFlag(
            conversation_id=r["conversation_id"],
            prompt_variant=r["prompt_variant"],
            scenario_id=r["scenario_id"],
            scenario_name=r["scenario_name"],
            overall_score=float(r["overall_score"]),
            goal_completion_score=r["goal_completion_score"],
            avg_total_latency_ms=_f(r["avg_total_latency_ms"]),
        )
        for r in rows
    ]


# ------------------------------------------------------------------ conversation lists
_LIST_FROM = """
FROM conversations c
LEFT JOIN scenarios s ON s.id = c.scenario_id
LEFT JOIN evaluations e ON e.conversation_id = c.id
LEFT JOIN LATERAL (
    SELECT avg(total_latency_ms) AS avg_total FROM latency_metrics l WHERE l.conversation_id = c.id
) lm ON true
"""

_SORTS = {
    "recent": "c.started_at DESC",
    "score_asc": "e.overall_score ASC NULLS LAST, c.started_at DESC",
    "score_desc": "e.overall_score DESC NULLS LAST, c.started_at DESC",
}


def _list_query(
    db: Session,
    *,
    prompt_variant: str | None,
    scenario_id: str | None,
    category: str | None,
    goal_completed: bool | None,
    min_score: float | None,
    max_score: float | None,
    run_mode: str | None,
    source: str | None,
    benchmark_run_id: uuid.UUID | None,
    sort: str,
    limit: int,
    offset: int,
    with_reasoning: bool,
) -> tuple[list[dict], int]:
    where: list[str] = []
    params: dict[str, Any] = {}

    def add(clause: str, name: str, value: Any) -> None:
        if value is not None:
            where.append(clause)
            params[name] = value

    add("c.prompt_variant = :variant", "variant", prompt_variant)
    add("c.scenario_id = :scenario_id", "scenario_id", scenario_id)
    add("s.category = :category", "category", category)
    add("c.goal_completed = :goal_completed", "goal_completed", goal_completed)
    add("e.overall_score >= :min_score", "min_score", min_score)
    add("e.overall_score <= :max_score", "max_score", max_score)
    add("c.run_mode = :run_mode", "run_mode", run_mode)
    add("c.source = :source", "source", source)
    add("c.benchmark_run_id = :run_id", "run_id", benchmark_run_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    total = db.execute(text(f"SELECT count(*) {_LIST_FROM} {where_sql}"), params).scalar_one()
    rows = db.execute(
        text(f"""
            SELECT c.id, c.prompt_variant, c.source, c.run_mode, c.scenario_id,
                   s.name AS scenario_name, s.category, s.difficulty,
                   c.goal_completed, c.stop_reason,
                   e.goal_completion_score, e.objection_handling_score,
                   e.conversation_quality_score, e.overall_score, e.invented_claims,
                   {"e.reasoning," if with_reasoning else "NULL AS reasoning,"}
                   lm.avg_total AS avg_total_latency_ms,
                   (SELECT count(*) FROM turns t
                     WHERE t.conversation_id = c.id AND t.speaker = 'agent') AS turn_count,
                   c.started_at
            {_LIST_FROM}
            {where_sql}
            ORDER BY {_SORTS.get(sort, _SORTS["recent"])}
            LIMIT :limit OFFSET :offset
            """),
        {**params, "limit": limit, "offset": offset},
    ).mappings()
    return [dict(r) for r in rows], total


def _item_fields(r: dict) -> dict:
    return {
        "id": r["id"],
        "prompt_variant": r["prompt_variant"],
        "source": r["source"],
        "run_mode": r["run_mode"],
        "scenario_id": r["scenario_id"],
        "scenario_name": r["scenario_name"],
        "category": r["category"],
        "difficulty": r["difficulty"],
        "goal_completed": r["goal_completed"],
        "stop_reason": r["stop_reason"],
        "goal_completion_score": r["goal_completion_score"],
        "objection_handling_score": r["objection_handling_score"],
        "conversation_quality_score": r["conversation_quality_score"],
        "overall_score": _f(r["overall_score"]),
        "invented_claims": r["invented_claims"],
        "avg_total_latency_ms": _f(r["avg_total_latency_ms"]),
        "turn_count": r["turn_count"],
        "started_at": r["started_at"],
    }


def list_conversations(db: Session, **filters: Any) -> ConversationList:
    rows, total = _list_query(db, with_reasoning=False, **filters)
    return ConversationList(
        items=[ConversationListItem(**_item_fields(r)) for r in rows], total=total
    )


def list_evaluations(db: Session, **filters: Any) -> EvaluationList:
    # Evaluations only exist for evaluated conversations.
    rows, total = _list_query(db, with_reasoning=True, **filters)
    return EvaluationList(
        items=[EvaluationListItem(**_item_fields(r), reasoning=r["reasoning"]) for r in rows],
        total=total,
    )


def conversation_detail(db: Session, conversation_id: uuid.UUID) -> ConversationDetail | None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        return None
    scenario = db.get(Scenario, conversation.scenario_id) if conversation.scenario_id else None
    turns = []
    totals: list[LatencyOut] = []
    for t in sorted(conversation.turns, key=lambda t: t.id):
        latency = None
        if t.latency is not None:
            latency = LatencyOut(
                stt_ms=t.latency.stt_latency_ms,
                llm_ms=t.latency.llm_latency_ms,
                tts_ms=t.latency.tts_latency_ms,
                total_ms=t.latency.total_latency_ms,
            )
            totals.append(latency)
        turns.append(
            TurnOut(
                id=t.id,
                turn_number=t.turn_number,
                speaker=t.speaker,
                text=t.text,
                created_at=t.created_at,
                latency_ms=t.latency_ms,
                latency=latency,
            )
        )
    summary = None
    if totals:

        def mean(values: list[float | None]) -> float | None:
            present = [v for v in values if v is not None]
            return sum(present) / len(present) if present else None

        summary = LatencyOut(
            stt_ms=mean([x.stt_ms for x in totals]),
            llm_ms=mean([x.llm_ms for x in totals]),
            tts_ms=mean([x.tts_ms for x in totals]),
            total_ms=sum(x.total_ms for x in totals) / len(totals),
        )
    ev = conversation.evaluation
    return ConversationDetail(
        id=conversation.id,
        prompt_variant=conversation.prompt_variant,
        prompt_hash=conversation.prompt_hash,
        source=conversation.source,
        run_mode=conversation.run_mode,
        llm_model=conversation.llm_model,
        stop_reason=conversation.stop_reason,
        started_at=conversation.started_at,
        completed_at=conversation.completed_at,
        goal_completed=conversation.goal_completed,
        scenario=ScenarioOut.model_validate(scenario, from_attributes=True) if scenario else None,
        turns=turns,
        evaluation=(
            EvaluationOut(
                goal_completion_score=ev.goal_completion_score,
                objection_handling_score=ev.objection_handling_score,
                conversation_quality_score=ev.conversation_quality_score,
                overall_score=float(ev.overall_score),
                invented_claims=ev.invented_claims,
                reasoning=ev.reasoning,
                judge_model=ev.judge_model,
            )
            if ev
            else None
        ),
        latency_summary=summary,
    )
