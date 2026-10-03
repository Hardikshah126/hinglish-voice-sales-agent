"""analytics views

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per *evaluated* conversation, with scenario attributes and mean per-turn latency.
    op.execute("""
        CREATE VIEW conversation_results AS
        SELECT
            c.id                         AS conversation_id,
            c.benchmark_run_id,
            c.run_mode,
            c.source,
            c.prompt_variant,
            c.scenario_id,
            s.name                       AS scenario_name,
            s.category,
            s.difficulty,
            c.goal_completed,
            c.stop_reason,
            c.started_at,
            e.goal_completion_score,
            e.objection_handling_score,
            e.conversation_quality_score,
            e.overall_score,
            e.invented_claims,
            e.reasoning,
            (SELECT count(*) FROM turns t
              WHERE t.conversation_id = c.id AND t.speaker = 'agent') AS agent_turns,
            lm.avg_stt_latency_ms,
            lm.avg_llm_latency_ms,
            lm.avg_tts_latency_ms,
            lm.avg_total_latency_ms
        FROM conversations c
        JOIN evaluations e ON e.conversation_id = c.id
        LEFT JOIN scenarios s ON s.id = c.scenario_id
        LEFT JOIN LATERAL (
            SELECT avg(stt_latency_ms)   AS avg_stt_latency_ms,
                   avg(llm_latency_ms)   AS avg_llm_latency_ms,
                   avg(tts_latency_ms)   AS avg_tts_latency_ms,
                   avg(total_latency_ms) AS avg_total_latency_ms
            FROM latency_metrics l
            WHERE l.conversation_id = c.id
        ) lm ON true
        """)
    # One row per agent turn with latency, for percentile queries.
    op.execute("""
        CREATE VIEW turn_latencies AS
        SELECT
            l.id AS latency_id,
            l.conversation_id,
            l.turn_id,
            c.benchmark_run_id,
            c.run_mode,
            c.prompt_variant,
            c.scenario_id,
            s.category,
            s.difficulty,
            l.source,
            l.stt_latency_ms,
            l.llm_latency_ms,
            l.tts_latency_ms,
            l.total_latency_ms
        FROM latency_metrics l
        JOIN conversations c ON c.id = l.conversation_id
        LEFT JOIN scenarios s ON s.id = c.scenario_id
        """)

    # The run that analysis queries target: the newest run with results, real before mock.
    op.execute("""
        CREATE VIEW latest_benchmark_run AS
        SELECT id, run_mode, status, started_at
        FROM benchmark_runs
        WHERE completed_conversations > 0
        ORDER BY (run_mode = 'real') DESC, started_at DESC
        LIMIT 1
        """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS latest_benchmark_run")
    op.execute("DROP VIEW IF EXISTS turn_latencies")
    op.execute("DROP VIEW IF EXISTS conversation_results")
