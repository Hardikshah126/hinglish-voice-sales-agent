"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("run_mode", sa.String(length=10), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_conversations", sa.Integer(), nullable=False),
        sa.Column("completed_conversations", sa.Integer(), nullable=False),
        sa.Column("failed_conversations", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("run_mode IN ('mock', 'real')", name="ck_benchmark_runs_mode"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'partial', 'failed')",
            name="ck_benchmark_runs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("customer_profile", sa.Text(), nullable=False),
        sa.Column("initial_message", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("completion_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_objection", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('discovery', 'price_objection', 'existing_solution', 'trust', 'timing', 'buying_intent', 'difficult_customer')",
            name="ck_scenarios_category",
        ),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name="ck_scenarios_difficulty"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scenarios_category", "scenarios", ["category"], unique=False)
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=True),
        sa.Column("benchmark_run_id", sa.UUID(), nullable=True),
        sa.Column("prompt_variant", sa.String(length=20), nullable=False),
        sa.Column("prompt_hash", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("run_mode", sa.String(length=10), nullable=False),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("stop_reason", sa.String(length=20), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("goal_completed", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "prompt_variant IN ('zero_shot', 'few_shot', 'persona')",
            name="ck_conversations_variant",
        ),
        sa.CheckConstraint("run_mode IN ('mock', 'real')", name="ck_conversations_mode"),
        sa.CheckConstraint("source IN ('voice', 'benchmark')", name="ck_conversations_source"),
        sa.CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN ('goal_reached', 'customer_left', 'max_turns', 'error')",
            name="ck_conversations_stop_reason",
        ),
        sa.ForeignKeyConstraint(["benchmark_run_id"], ["benchmark_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "benchmark_run_id", "scenario_id", "prompt_variant", name="uq_conversations_run_cell"
        ),
    )
    op.create_index(
        "ix_conversations_benchmark_run_id", "conversations", ["benchmark_run_id"], unique=False
    )
    op.create_index(
        "ix_conversations_prompt_variant", "conversations", ["prompt_variant"], unique=False
    )
    op.create_index(
        "ix_conversations_run_mode_source", "conversations", ["run_mode", "source"], unique=False
    )
    op.create_index("ix_conversations_scenario_id", "conversations", ["scenario_id"], unique=False)
    op.create_table(
        "evaluations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("goal_completion_score", sa.SmallInteger(), nullable=False),
        sa.Column("objection_handling_score", sa.SmallInteger(), nullable=True),
        sa.Column("conversation_quality_score", sa.SmallInteger(), nullable=False),
        sa.Column("overall_score", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("invented_claims", sa.Boolean(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("judge_model", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "conversation_quality_score BETWEEN 1 AND 5", name="ck_evaluations_quality"
        ),
        sa.CheckConstraint("goal_completion_score BETWEEN 0 AND 2", name="ck_evaluations_goal"),
        sa.CheckConstraint(
            "objection_handling_score IS NULL OR objection_handling_score BETWEEN 0 AND 3",
            name="ck_evaluations_objection",
        ),
        sa.CheckConstraint("overall_score BETWEEN 0 AND 5", name="ck_evaluations_overall"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_evaluations_conversation"),
    )
    op.create_table(
        "turns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.CheckConstraint("speaker IN ('customer', 'agent')", name="ck_turns_speaker"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_turns_latency"),
        sa.CheckConstraint("turn_number >= 1", name="ck_turns_turn_number"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "turn_number", "speaker", name="uq_turns_position"),
    )
    op.create_index("ix_turns_conversation_id", "turns", ["conversation_id"], unique=False)
    op.create_table(
        "latency_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.BigInteger(), nullable=False),
        sa.Column("stt_latency_ms", sa.Float(), nullable=True),
        sa.Column("llm_latency_ms", sa.Float(), nullable=True),
        sa.Column("tts_latency_ms", sa.Float(), nullable=True),
        sa.Column("total_latency_ms", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('voice', 'benchmark')", name="ck_latency_source"),
        sa.CheckConstraint(
            "(stt_latency_ms IS NULL OR stt_latency_ms >= 0) AND (llm_latency_ms IS NULL OR llm_latency_ms >= 0) AND (tts_latency_ms IS NULL OR tts_latency_ms >= 0) AND total_latency_ms >= 0",
            name="ck_latency_non_negative",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id", name="uq_latency_metrics_turn"),
    )
    op.create_index(
        "ix_latency_metrics_conversation_id", "latency_metrics", ["conversation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_latency_metrics_conversation_id", table_name="latency_metrics")
    op.drop_table("latency_metrics")
    op.drop_index("ix_turns_conversation_id", table_name="turns")
    op.drop_table("turns")
    op.drop_table("evaluations")
    op.drop_index("ix_conversations_scenario_id", table_name="conversations")
    op.drop_index("ix_conversations_run_mode_source", table_name="conversations")
    op.drop_index("ix_conversations_prompt_variant", table_name="conversations")
    op.drop_index("ix_conversations_benchmark_run_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_scenarios_category", table_name="scenarios")
    op.drop_table("scenarios")
    op.drop_table("benchmark_runs")
