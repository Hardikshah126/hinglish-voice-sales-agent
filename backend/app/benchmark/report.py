"""Generates reports/benchmark_report.md from whatever is in the database.

Every number is read from PostgreSQL. Observations are derived mechanically from the
data (no hand-written conclusions), and mock runs are labelled as such.
"""

import math
import statistics
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app import analytics
from app.prompts.registry import PROMPT_REGISTRY
from app.schemas import EvaluationSummary, VariantSummary

MOCK_DISCLAIMER = (
    "> **MOCK RESULTS.** These results were generated using mock providers and are not "
    "representative of production model performance. They only demonstrate that the benchmark "
    "pipeline (simulation, evaluation, storage, analytics) works end to end."
)

TITLES = {"zero_shot": "Zero-shot", "few_shot": "Few-shot", "persona": "Persona"}


def _fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.{digits}f}{suffix}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _variant_row(label: str, getter, variants: list[VariantSummary]) -> list[str]:
    return [label, *[getter(v) for v in variants]]


def _paired_wins(summary: EvaluationSummary) -> list[list[str]]:
    """Pairwise wins/ties/losses of overall score, scenario by scenario."""
    scores: dict[str, dict[str, float]] = {}
    for row in summary.scenario_matrix:
        scores[row.scenario_id] = {c.prompt_variant: c.overall_score for c in row.cells}
    variants = [v.prompt_variant for v in summary.by_variant]
    rows = []
    for i, a in enumerate(variants):
        for b in variants[i + 1 :]:
            pairs = [(s[a], s[b]) for s in scores.values() if a in s and b in s]
            wins = sum(x > y for x, y in pairs)
            losses = sum(x < y for x, y in pairs)
            rows.append(
                [
                    f"{TITLES[a]} vs {TITLES[b]}",
                    str(wins),
                    str(len(pairs) - wins - losses),
                    str(losses),
                ]
            )
    return rows


def _std_error(values: list[float]) -> float | None:
    return statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None


def generate_report(
    db: Session, run_id: uuid.UUID | None = None, run_mode: str | None = None
) -> str:
    s = analytics.evaluation_summary(db, run_id=run_id, run_mode=run_mode)
    lines: list[str] = ["# Benchmark Report", ""]
    if s.benchmark_run is None:
        return "\n".join([*lines, "Benchmark not yet run.", ""])

    run = s.benchmark_run
    variants = s.by_variant
    if s.is_mock:
        lines += [MOCK_DISCLAIMER, ""]
    lines += [
        f"- Run id: `{run.id}`",
        f"- Provider mode: **{run.run_mode.upper()}**",
        "- Models: "
        + ", ".join(f"{role} `{model}`" for role, model in run.config.get("models", {}).items()),
        f"- Status: {run.status} — {run.completed_conversations} of "
        f"{run.total_conversations} conversations completed, {run.failed_conversations} failed",
        f"- Generated: {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}",
        "",
        "## Dataset",
        "",
        f"{s.scenarios} scenarios across 7 categories (discovery, price objections, existing "
        "solutions, trust, timing, buying intent, difficult customers), difficulty 1-5. "
        f"{s.conversations} evaluated conversations in this run.",
        "",
        "## Prompt Strategies",
        "",
        *[f"- **{p.title}**: {p.description}" for p in PROMPT_REGISTRY.values()],
        "",
        "All three share an identical base brief (product facts, objective, language "
        "requirement, constraints); only the strategy-specific layer differs.",
        "",
        "## Methodology",
        "",
        "- Every scenario is run once per strategy against the **same customer simulator** "
        "(same model, temperature and seed). The simulator never sees the strategy.",
        "- Up to 8 turns (customer message + agent reply); the conversation stops early once "
        "the simulated customer clearly agrees to the scenario goal or walks away.",
        "- Each conversation is scored by one LLM judge with a fixed rubric (goal completion "
        "0-2, objection handling 0-3 or N/A, conversation quality 1-5, invented-claims flag). "
        "The judge sees the scenario and transcript only, never the strategy.",
        "- Overall score (0-5) = weighted mean of normalised dimensions "
        "(goal 0.4, objection 0.3, quality 0.3; objection weight dropped when N/A).",
        "- Latency is measured with a monotonic clock around each provider call. "
        + analytics.LATENCY_NOTE,
        "",
    ]

    headers = ["Metric", *[TITLES[v.prompt_variant] for v in variants]]
    lines += ["## Goal Completion", ""]
    lines += [
        _table(
            headers,
            [
                _variant_row(
                    "Goal completion rate",
                    lambda v: f"{100 * v.goal_completion_rate:.1f}% ({v.completed_goals}/{v.conversations})",
                    variants,
                ),
                _variant_row("Mean goal score (0-2)", lambda v: _fmt(v.avg_goal_score), variants),
            ],
        ),
        "",
        "## Objection Handling",
        "",
        _table(
            headers,
            [
                _variant_row("Mean score (0-3)", lambda v: _fmt(v.avg_objection_score), variants),
                _variant_row(
                    "Conversations with an objection", lambda v: str(v.objection_samples), variants
                ),
            ],
        ),
        "",
        "## Conversation Quality",
        "",
        _table(
            headers,
            [
                _variant_row("Mean quality (1-5)", lambda v: _fmt(v.avg_quality_score), variants),
                _variant_row("Mean overall (0-5)", lambda v: _fmt(v.avg_overall_score), variants),
                _variant_row(
                    "Conversations with invented claims",
                    lambda v: str(v.invented_claims_count),
                    variants,
                ),
            ],
        ),
        "",
        "## Latency",
        "",
        _table(
            headers,
            [
                _variant_row("Avg total (ms)", lambda v: _fmt(v.latency.avg_total_ms, 1), variants),
                _variant_row("P50 total (ms)", lambda v: _fmt(v.latency.p50_total_ms, 1), variants),
                _variant_row("P95 total (ms)", lambda v: _fmt(v.latency.p95_total_ms, 1), variants),
                _variant_row("Avg LLM (ms)", lambda v: _fmt(v.latency.avg_llm_ms, 1), variants),
                _variant_row("Avg TTS (ms)", lambda v: _fmt(v.latency.avg_tts_ms, 1), variants),
                _variant_row("Agent turns measured", lambda v: str(v.latency.samples), variants),
            ],
        ),
        "",
        "STT latency is not part of benchmark runs (customer input is text). Real "
        "end-to-end voice latency is recorded separately for live conversations "
        "(`source = 'voice'`, see query 17 in `sql/analysis.sql`).",
        "",
        "## Scenario Analysis",
        "",
    ]

    by_cat: dict[str, dict[str, float]] = {}
    for g in s.by_category:
        by_cat.setdefault(g.group, {})[g.prompt_variant] = g.avg_overall_score
    lines += [
        _table(
            ["Category", *[TITLES[v.prompt_variant] for v in variants]],
            [
                [
                    cat.replace("_", " ").title(),
                    *[_fmt(scores.get(v.prompt_variant)) for v in variants],
                ]
                for cat, scores in by_cat.items()
            ],
        ),
        "",
        "Mean overall score (0-5) per scenario:",
        "",
        _table(
            ["Scenario", "Category", "Diff.", *[TITLES[v.prompt_variant] for v in variants]],
            [
                [
                    row.scenario_name,
                    row.category.replace("_", " "),
                    str(row.difficulty),
                    *[
                        _fmt(
                            next(
                                (
                                    c.overall_score
                                    for c in row.cells
                                    if c.prompt_variant == v.prompt_variant
                                ),
                                None,
                            )
                        )
                        for v in variants
                    ],
                ]
                for row in s.scenario_matrix
            ],
        ),
        "",
        "Paired comparison of overall score across scenarios (wins / ties / losses for the first strategy):",
        "",
        _table(["Comparison", "Wins", "Ties", "Losses"], _paired_wins(s)),
        "",
        "## Failure Cases",
        "",
    ]
    if s.failure_cases:
        lines += [
            _table(
                ["Strategy", "Scenario", "Goal", "Overall", "Conversation"],
                [
                    [
                        TITLES[f.prompt_variant],
                        f.scenario_name or "-",
                        f"{f.goal_completion_score}/2",
                        _fmt(f.overall_score),
                        f"`{f.conversation_id}`",
                    ]
                    for f in s.failure_cases
                ],
            ),
            "",
        ]
    else:
        lines += ["No conversation had goal score 0 or overall score below 2.5.", ""]

    lines += ["## Interesting Observations", "", *_observations(s), ""]
    lines += [
        "## Limitations",
        "",
        "- One run per scenario/strategy cell with a stochastic simulator: no confidence "
        "intervals beyond the standard errors below, and differences of a few tenths of a "
        "point on 25 scenarios should not be treated as significant.",
        "- The judge is an LLM and may share biases with the agent model; no human "
        "calibration set has been collected yet.",
        "- The simulator is a model playing a customer, not real customers.",
        "- Benchmark latency excludes STT and network conditions of real users.",
        "- Scenarios are written for one fictional product (FlowDesk).",
        "",
        "Standard error of mean overall score: "
        + ", ".join(
            f"{TITLES[v.prompt_variant]} ±{_fmt(_std_error([c.overall_score for r in s.scenario_matrix for c in r.cells if c.prompt_variant == v.prompt_variant]), 2)}"
            for v in variants
        ),
        "",
        "## Next Experiments",
        "",
        "- Repeat each cell with several simulator seeds and report variance.",
        "- Use a different model family as judge and measure judge agreement.",
        "- Add a human-labelled calibration set of 20-30 conversations.",
        "- Combine few-shot and persona, and ablate the number of examples.",
        "- Measure real voice latency across devices and networks.",
        "",
    ]
    if s.is_mock:
        lines += ["---", "", MOCK_DISCLAIMER, ""]
    return "\n".join(lines)


def _observations(s: EvaluationSummary) -> list[str]:
    if s.is_mock:
        return [
            "Mock providers use rule-based logic, so no conclusion about prompt strategies "
            "can be drawn from these numbers. Run the benchmark with a real API key to "
            "produce observations."
        ]
    obs: list[str] = []
    v = s.by_variant
    best = max(v, key=lambda x: x.avg_overall_score)
    worst = min(v, key=lambda x: x.avg_overall_score)
    obs.append(
        f"Highest mean overall score: {TITLES[best.prompt_variant]} "
        f"({best.avg_overall_score:.2f}); lowest: {TITLES[worst.prompt_variant]} "
        f"({worst.avg_overall_score:.2f})."
    )
    fastest = min(
        (x for x in v if x.latency.avg_total_ms is not None),
        key=lambda x: x.latency.avg_total_ms or 0,
        default=None,
    )
    if fastest:
        obs.append(
            f"Lowest mean per-turn latency: {TITLES[fastest.prompt_variant]} "
            f"({_fmt(fastest.latency.avg_total_ms, 0)} ms)."
        )
    flagged = [x for x in v if x.invented_claims_count]
    if flagged:
        obs.append(
            "Invented-claims flags: "
            + ", ".join(f"{TITLES[x.prompt_variant]} {x.invented_claims_count}" for x in flagged)
            + "."
        )
    spreads = sorted(
        (
            (max(c.overall_score for c in r.cells) - min(c.overall_score for c in r.cells), r)
            for r in s.scenario_matrix
            if len(r.cells) > 1
        ),
        key=lambda t: -t[0],
    )
    if spreads and spreads[0][0] > 0:
        spread, row = spreads[0]
        obs.append(
            f"Largest between-strategy spread: {row.scenario_name} "
            f"({spread:.2f} points between best and worst strategy)."
        )
    return [f"- {o}" for o in obs]
