"""SQLAlchemy models. The Alembic migration in alembic/versions mirrors these definitions."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain import (
    SCENARIO_CATEGORIES,
    ConversationSource,
    PromptVariant,
    RunMode,
    RunStatus,
    Speaker,
    StopReason,
    sql_in,
)


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now().astimezone()


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({sql_in(SCENARIO_CATEGORIES)})", name="ck_scenarios_category"
        ),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="ck_scenarios_difficulty"),
        Index("ix_scenarios_category", "category"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    customer_profile: Mapped[str] = mapped_column(Text, nullable=False)
    initial_message: Mapped[str] = mapped_column(Text, nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    completion_criteria: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    expected_objection: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(RunStatus)})", name="ck_benchmark_runs_status"),
        CheckConstraint(f"run_mode IN ({sql_in(RunMode)})", name="ck_benchmark_runs_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    run_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    total_conversations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_conversations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_conversations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            f"prompt_variant IN ({sql_in(PromptVariant)})", name="ck_conversations_variant"
        ),
        CheckConstraint(f"run_mode IN ({sql_in(RunMode)})", name="ck_conversations_mode"),
        CheckConstraint(
            f"source IN ({sql_in(ConversationSource)})", name="ck_conversations_source"
        ),
        CheckConstraint(
            f"stop_reason IS NULL OR stop_reason IN ({sql_in(StopReason)})",
            name="ck_conversations_stop_reason",
        ),
        UniqueConstraint(
            "benchmark_run_id", "scenario_id", "prompt_variant", name="uq_conversations_run_cell"
        ),
        Index("ix_conversations_scenario_id", "scenario_id"),
        Index("ix_conversations_prompt_variant", "prompt_variant"),
        Index("ix_conversations_benchmark_run_id", "benchmark_run_id"),
        Index("ix_conversations_run_mode_source", "run_mode", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NULL for free-form live voice conversations that are not tied to a scenario.
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id", ondelete="RESTRICT"))
    benchmark_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benchmark_runs.id", ondelete="CASCADE")
    )
    prompt_variant: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    run_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    llm_model: Mapped[str | None] = mapped_column(String(100))
    stop_reason: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    goal_completed: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scenario: Mapped[Scenario | None] = relationship()
    turns: Mapped[list["Turn"]] = relationship(
        back_populates="conversation",
        order_by="Turn.id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    evaluation: Mapped["Evaluation | None"] = relationship(
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        CheckConstraint(f"speaker IN ({sql_in(Speaker)})", name="ck_turns_speaker"),
        CheckConstraint("turn_number >= 1", name="ck_turns_turn_number"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_turns_latency"),
        UniqueConstraint("conversation_id", "turn_number", "speaker", name="uq_turns_position"),
        Index("ix_turns_conversation_id", "conversation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # One "turn" is a customer message plus the agent's reply; both share the number.
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(10), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    latency_ms: Mapped[float | None] = mapped_column(Float)

    conversation: Mapped[Conversation] = relationship(back_populates="turns")
    latency: Mapped["LatencyMetric | None"] = relationship(
        back_populates="turn", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint("goal_completion_score BETWEEN 0 AND 2", name="ck_evaluations_goal"),
        CheckConstraint(
            "objection_handling_score IS NULL OR objection_handling_score BETWEEN 0 AND 3",
            name="ck_evaluations_objection",
        ),
        CheckConstraint(
            "conversation_quality_score BETWEEN 1 AND 5", name="ck_evaluations_quality"
        ),
        CheckConstraint("overall_score BETWEEN 0 AND 5", name="ck_evaluations_overall"),
        UniqueConstraint("conversation_id", name="uq_evaluations_conversation"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    goal_completion_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # NULL = no objection was raised in the conversation, so the dimension is not applicable.
    objection_handling_score: Mapped[int | None] = mapped_column(SmallInteger)
    conversation_quality_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    overall_score: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    invented_claims: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    judge_model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="evaluation")


class LatencyMetric(Base):
    __tablename__ = "latency_metrics"
    __table_args__ = (
        CheckConstraint(f"source IN ({sql_in(ConversationSource)})", name="ck_latency_source"),
        CheckConstraint(
            "(stt_latency_ms IS NULL OR stt_latency_ms >= 0) AND "
            "(llm_latency_ms IS NULL OR llm_latency_ms >= 0) AND "
            "(tts_latency_ms IS NULL OR tts_latency_ms >= 0) AND total_latency_ms >= 0",
            name="ck_latency_non_negative",
        ),
        UniqueConstraint("turn_id", name="uq_latency_metrics_turn"),
        Index("ix_latency_metrics_conversation_id", "conversation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id", ondelete="CASCADE"), nullable=False)
    # NULL means the stage was not exercised (e.g. no STT in text-only benchmark runs).
    stt_latency_ms: Mapped[float | None] = mapped_column(Float)
    llm_latency_ms: Mapped[float | None] = mapped_column(Float)
    tts_latency_ms: Mapped[float | None] = mapped_column(Float)
    total_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    turn: Mapped[Turn] = relationship(back_populates="latency")
