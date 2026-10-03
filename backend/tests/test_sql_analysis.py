"""Executes every statement in sql/analysis.sql against real benchmark data."""

import re
from pathlib import Path

import pytest
from sqlalchemy import text

from app.benchmark.runner import BenchmarkConfig, create_run, execute_run
from app.config import Settings
from app.db.session import get_engine, get_sessionmaker

SQL_FILE = Path(__file__).resolve().parents[2] / "sql" / "analysis.sql"


def statements() -> list[str]:
    body = "\n".join(
        line
        for line in SQL_FILE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    )
    return [s.strip() for s in body.split(";") if s.strip()]


@pytest.fixture
def benchmark_run(providers):
    factory = get_sessionmaker()
    config = BenchmarkConfig(
        scenario_ids=("disc-excel", "price-expensive", "diff-one-word", "intent-demo")
    )
    run_id = create_run(factory, providers, config)
    execute_run(factory, providers, Settings(_env_file=None), run_id)
    return run_id


def test_file_contains_the_required_queries():
    text_ = SQL_FILE.read_text(encoding="utf-8").lower()
    for needle in (
        "average overall score",
        "goal completion rate",
        "objection handling",
        "conversation quality",
        "average latency",
        "p50",
        "p95",
        "by scenario",
        "difficulty",
        "category",
        "matrix",
        "failure cases",
        "high-latency",
        "completed demos",
        "distribution of scores",
    ):
        assert needle in text_, needle
    assert len(statements()) >= 15


def test_every_query_runs_on_empty_database():
    with get_engine().connect() as conn:
        for stmt in statements():
            conn.execute(text(stmt)).fetchall()


def test_every_query_runs_and_returns_data_after_a_benchmark(benchmark_run):
    non_empty = 0
    with get_engine().connect() as conn:
        for stmt in statements():
            rows = conn.execute(text(stmt)).fetchall()
            non_empty += bool(rows)
    assert non_empty >= 14  # failure cases / voice latency may legitimately be empty


def test_sql_and_api_agree_on_goal_completion(benchmark_run, client):
    with get_engine().connect() as conn:
        sql_rates = dict(conn.execute(text("""
                    SELECT prompt_variant,
                           round(100.0 * count(*) FILTER (WHERE goal_completion_score = 2) / count(*), 1)
                    FROM conversation_results
                    WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
                    GROUP BY prompt_variant
                    """)).fetchall())
    api = client.get("/api/evaluations/summary").json()["by_variant"]
    for v in api:
        assert round(100 * v["goal_completion_rate"], 1) == float(sql_rates[v["prompt_variant"]])


def test_percentile_queries_are_ordered(benchmark_run):
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
                SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total_latency_ms),
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY total_latency_ms)
                FROM turn_latencies
                """)).one()
    assert rows[0] <= rows[1]


def test_no_semicolons_in_strings_break_the_splitter():
    assert not any(re.search(r"'[^']*;[^']*'", s) for s in statements())
