import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import repository
from app.db.models import Conversation, Evaluation, LatencyMetric, Scenario, Turn
from app.domain import ConversationSource, PromptVariant, RunMode
from app.evaluation.evaluator import EvaluationResult
from app.scenarios.loader import seed_scenarios


def make_conversation(db, scenario_id="disc-excel", variant=PromptVariant.PERSONA):
    seed_scenarios(db)
    return repository.create_conversation(
        db,
        variant=variant,
        source=ConversationSource.BENCHMARK,
        run_mode=RunMode.MOCK,
        llm_model="mock-llm",
        scenario_id=scenario_id,
    )


def exchange(db, conversation, n=1):
    return repository.add_exchange(
        db,
        conversation,
        turn_number=n,
        customer_text="Hum Excel use karte hain.",
        agent_text="Haan, samajh sakta hoon.",
        source=ConversationSource.BENCHMARK,
        stt_ms=None,
        llm_ms=12.5,
        tts_ms=30.1,
        total_ms=43.0,
    )


def result(**overrides) -> EvaluationResult:
    base = dict(
        goal_completion_score=2,
        objection_handling_score=3,
        conversation_quality_score=4,
        overall_score=4.6,
        invented_claims=False,
        reasoning="Good.",
        judge_model="judge",
    )
    return EvaluationResult(**{**base, **overrides})


def test_conversation_inserts_with_defaults(db):
    conv = make_conversation(db)
    db.commit()
    row = db.get(Conversation, conv.id)
    assert row.prompt_variant == "persona"
    assert row.created_at is not None and row.started_at is not None
    assert row.prompt_hash


def test_turns_and_latency_insert_and_link(db):
    conv = make_conversation(db)
    agent_turn = exchange(db, conv)
    db.commit()
    turns = db.scalars(select(Turn).where(Turn.conversation_id == conv.id).order_by(Turn.id)).all()
    assert [t.speaker for t in turns] == ["customer", "agent"]
    metric = db.scalars(select(LatencyMetric)).one()
    assert metric.turn_id == agent_turn.id
    assert metric.stt_latency_ms is None and metric.total_latency_ms == 43.0
    assert agent_turn.latency_ms == 43.0


def test_evaluation_inserts_and_sets_goal_completed(db):
    conv = make_conversation(db)
    repository.save_evaluation(db, conv, result(), completed_at=conv.started_at)
    db.commit()
    ev = db.scalars(select(Evaluation)).one()
    assert float(ev.overall_score) == 4.6
    assert db.get(Conversation, conv.id).goal_completed is True
    assert db.get(Conversation, conv.id).completed_at is not None


def test_load_state_round_trips_history(db):
    conv = make_conversation(db)
    exchange(db, conv, 1)
    exchange(db, conv, 2)
    db.commit()
    db.refresh(conv)
    state = repository.load_state(conv)
    assert len(state.messages) == 4
    assert state.customer_turns == 2
    assert repository.next_turn_number(db, conv.id) == 3


def test_invalid_prompt_variant_is_rejected(db):
    seed_scenarios(db)
    db.add(
        Conversation(
            prompt_variant="telepathy",
            prompt_hash="x",
            source="voice",
            run_mode="mock",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_duplicate_turn_position_is_rejected(db):
    conv = make_conversation(db)
    exchange(db, conv, 1)
    db.commit()
    with pytest.raises(IntegrityError):
        exchange(db, conv, 1)
        db.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"goal_completion_score": 3},
        {"objection_handling_score": 4},
        {"conversation_quality_score": 0},
        {"overall_score": 5.5},
    ],
)
def test_score_range_constraints(db, overrides):
    conv = make_conversation(db)
    with pytest.raises(IntegrityError):
        repository.save_evaluation(db, conv, result(**overrides), completed_at=conv.started_at)


def test_one_evaluation_per_conversation(db):
    conv = make_conversation(db)
    repository.save_evaluation(db, conv, result(), completed_at=conv.started_at)
    db.commit()
    with pytest.raises(IntegrityError):
        repository.save_evaluation(db, conv, result(), completed_at=conv.started_at)


def test_negative_latency_is_rejected(db):
    conv = make_conversation(db)
    with pytest.raises(IntegrityError):
        repository.add_exchange(
            db,
            conv,
            turn_number=1,
            customer_text="a",
            agent_text="b",
            source=ConversationSource.BENCHMARK,
            stt_ms=None,
            llm_ms=-1.0,
            tts_ms=None,
            total_ms=1.0,
        )


def test_foreign_keys_enforced(db):
    db.add(
        Turn(
            conversation_id="00000000-0000-0000-0000-000000000000",
            turn_number=1,
            speaker="agent",
            text="x",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_deleting_a_conversation_cascades(db):
    conv = make_conversation(db)
    exchange(db, conv)
    repository.save_evaluation(db, conv, result(), completed_at=conv.started_at)
    db.commit()
    db.delete(conv)
    db.commit()
    for model in (Turn, Evaluation, LatencyMetric):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert db.scalar(select(func.count()).select_from(Scenario)) == 25  # scenarios survive


def test_scenario_cannot_be_deleted_while_referenced(db):
    conv = make_conversation(db)
    db.commit()
    db.delete(db.get(Scenario, conv.scenario_id))
    with pytest.raises(IntegrityError):
        db.flush()
