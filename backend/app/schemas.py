"""Pydantic request / response models for the HTTP API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain import PromptVariant


class LatencyOut(BaseModel):
    stt_ms: float | None = None
    llm_ms: float | None = None
    tts_ms: float | None = None
    total_ms: float


class VoiceRespondResponse(BaseModel):
    conversation_id: uuid.UUID
    transcript: str
    response_text: str
    audio_url: str | None
    latency: LatencyOut
    warnings: list[str] = []
    mock_mode: bool  # true if ANY component (stt/llm/tts) is a mock
    mock_components: list[str] = []
    speak_client_side: bool = False  # browser should speak response_text


class ConversationCreate(BaseModel):
    prompt_variant: PromptVariant
    scenario_id: str | None = Field(default=None, max_length=64)


class ScenarioOut(BaseModel):
    id: str
    name: str
    category: str
    description: str
    customer_profile: str
    initial_message: str
    goal: str
    completion_criteria: list[str]
    expected_objection: str | None
    difficulty: int


class TurnOut(BaseModel):
    id: int
    turn_number: int
    speaker: str
    text: str
    created_at: datetime
    latency_ms: float | None
    latency: LatencyOut | None = None


class EvaluationOut(BaseModel):
    goal_completion_score: int
    objection_handling_score: int | None
    conversation_quality_score: int
    overall_score: float
    invented_claims: bool
    reasoning: str
    judge_model: str


class ConversationDetail(BaseModel):
    id: uuid.UUID
    prompt_variant: str
    prompt_hash: str
    source: str
    run_mode: str
    llm_model: str | None
    stop_reason: str | None
    started_at: datetime
    completed_at: datetime | None
    goal_completed: bool | None
    scenario: ScenarioOut | None
    turns: list[TurnOut]
    evaluation: EvaluationOut | None
    latency_summary: LatencyOut | None


class ConversationListItem(BaseModel):
    id: uuid.UUID
    prompt_variant: str
    source: str
    run_mode: str
    scenario_id: str | None
    scenario_name: str | None
    category: str | None
    difficulty: int | None
    goal_completed: bool | None
    stop_reason: str | None
    goal_completion_score: int | None
    objection_handling_score: int | None
    conversation_quality_score: int | None
    overall_score: float | None
    invented_claims: bool | None
    avg_total_latency_ms: float | None
    turn_count: int
    started_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationListItem]
    total: int


class EvaluationListItem(ConversationListItem):
    reasoning: str | None


class EvaluationList(BaseModel):
    items: list[EvaluationListItem]
    total: int


class BenchmarkRunOut(BaseModel):
    id: uuid.UUID
    status: str
    run_mode: str
    total_conversations: int
    completed_conversations: int
    failed_conversations: int
    error: str | None
    started_at: datetime
    completed_at: datetime | None
    config: dict


class BenchmarkStatus(BaseModel):
    llm_provider: str
    models: dict[str, str]
    is_running: bool
    scenario_count: int
    variants: list[str]
    latest_run: BenchmarkRunOut | None
    runs: list[BenchmarkRunOut]


class BenchmarkRunRequest(BaseModel):
    variants: list[PromptVariant] | None = None
    scenario_ids: list[str] | None = Field(default=None, max_length=100)
    include_tts: bool | None = None
    max_turns: int | None = Field(default=None, ge=1, le=8)


class BenchmarkRunStarted(BaseModel):
    run_id: uuid.UUID
    status: str
    run_mode: str
    total_conversations: int


class LatencyStats(BaseModel):
    avg_total_ms: float | None
    p50_total_ms: float | None
    p95_total_ms: float | None
    avg_llm_ms: float | None
    avg_tts_ms: float | None
    avg_stt_ms: float | None
    samples: int


class VariantSummary(BaseModel):
    prompt_variant: str
    conversations: int
    goal_completion_rate: float
    avg_goal_score: float
    avg_objection_score: float | None
    objection_samples: int
    avg_quality_score: float
    avg_overall_score: float
    completed_goals: int
    invented_claims_count: int
    latency: LatencyStats


class GroupedScore(BaseModel):
    group: str
    prompt_variant: str
    conversations: int
    avg_overall_score: float
    goal_completion_rate: float


class MatrixCell(BaseModel):
    prompt_variant: str
    overall_score: float
    goal_completion_score: int
    objection_handling_score: int | None
    conversation_quality_score: int
    conversation_id: uuid.UUID


class ScenarioRow(BaseModel):
    scenario_id: str
    scenario_name: str
    category: str
    difficulty: int
    cells: list[MatrixCell]


class ScoreDistribution(BaseModel):
    metric: Literal["goal", "objection", "quality"]
    prompt_variant: str
    score: int
    count: int


class ConversationFlag(BaseModel):
    conversation_id: uuid.UUID
    prompt_variant: str
    scenario_id: str | None
    scenario_name: str | None
    overall_score: float
    goal_completion_score: int
    avg_total_latency_ms: float | None


class EvaluationSummary(BaseModel):
    benchmark_run: BenchmarkRunOut | None
    run_mode: str | None
    is_mock: bool
    available_modes: list[str]
    conversations: int
    scenarios: int
    prompt_variants: int
    by_variant: list[VariantSummary]
    by_category: list[GroupedScore]
    by_difficulty: list[GroupedScore]
    scenario_matrix: list[ScenarioRow]
    distributions: list[ScoreDistribution]
    failure_cases: list[ConversationFlag]
    high_latency: list[ConversationFlag]
    latency_note: str
