"""Small persistence helpers shared by the voice pipeline and the benchmark runner."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.sales_agent import ConversationState, Message
from app.db.models import Conversation, Evaluation, LatencyMetric, Turn
from app.domain import ConversationSource, PromptVariant, RunMode, Speaker
from app.evaluation.evaluator import EvaluationResult
from app.prompts.registry import get_system_prompt, prompt_hash


def create_conversation(
    db: Session,
    *,
    variant: PromptVariant,
    source: ConversationSource,
    run_mode: RunMode,
    llm_model: str | None,
    scenario_id: str | None = None,
    benchmark_run_id: uuid.UUID | None = None,
) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        scenario_id=scenario_id,
        benchmark_run_id=benchmark_run_id,
        prompt_variant=variant.value,
        prompt_hash=prompt_hash(get_system_prompt(variant)),
        source=source.value,
        run_mode=run_mode.value,
        llm_model=llm_model,
    )
    db.add(conversation)
    db.flush()
    return conversation


def next_turn_number(db: Session, conversation_id: uuid.UUID) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(Turn)
        .where(Turn.conversation_id == conversation_id, Turn.speaker == Speaker.CUSTOMER.value)
    )
    return (count or 0) + 1


def add_exchange(
    db: Session,
    conversation: Conversation,
    *,
    turn_number: int,
    customer_text: str,
    agent_text: str,
    source: ConversationSource,
    stt_ms: float | None,
    llm_ms: float | None,
    tts_ms: float | None,
    total_ms: float,
) -> Turn:
    """Persist one customer message + agent reply, plus the agent turn's latency breakdown."""
    db.add(
        Turn(
            conversation_id=conversation.id,
            turn_number=turn_number,
            speaker=Speaker.CUSTOMER.value,
            text=customer_text,
        )
    )
    agent_turn = Turn(
        conversation_id=conversation.id,
        turn_number=turn_number,
        speaker=Speaker.AGENT.value,
        text=agent_text,
        latency_ms=total_ms,
    )
    db.add(agent_turn)
    db.flush()
    db.add(
        LatencyMetric(
            conversation_id=conversation.id,
            turn_id=agent_turn.id,
            stt_latency_ms=stt_ms,
            llm_latency_ms=llm_ms,
            tts_latency_ms=tts_ms,
            total_latency_ms=total_ms,
            source=source.value,
        )
    )
    db.flush()
    return agent_turn


def save_evaluation(
    db: Session, conversation: Conversation, result: EvaluationResult, completed_at: datetime
) -> Evaluation:
    evaluation = Evaluation(
        conversation_id=conversation.id,
        goal_completion_score=result.goal_completion_score,
        objection_handling_score=result.objection_handling_score,
        conversation_quality_score=result.conversation_quality_score,
        overall_score=result.overall_score,
        invented_claims=result.invented_claims,
        reasoning=result.reasoning,
        judge_model=result.judge_model,
    )
    db.add(evaluation)
    conversation.goal_completed = result.goal_completed
    conversation.completed_at = completed_at
    db.flush()
    return evaluation


def load_state(conversation: Conversation) -> ConversationState:
    """Rebuild the in-memory conversation state from persisted turns."""
    state = ConversationState()
    for turn in sorted(conversation.turns, key=lambda t: t.id):
        state.messages.append(Message(Speaker(turn.speaker), turn.text))
    return state
