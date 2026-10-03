import json

import pytest

from app.agent.sales_agent import ConversationState
from app.config import Settings
from app.core.errors import LLMResponseError
from app.core.jsonutil import parse_json_object
from app.evaluation.evaluator import (
    ConversationEvaluator,
    build_judge_prompt,
    compute_overall,
)
from app.providers.mock_llm import MockLLMProvider
from app.scenarios.loader import get_scenario
from tests.helpers import RecordingLLM

GOOD = {
    "goal_completion_score": 2,
    "objection_handling_score": 3,
    "conversation_quality_score": 5,
    "invented_claims": False,
    "reasoning": "The agent acknowledged the pricing concern and offered the trial.",
}


@pytest.fixture
def settings():
    return Settings(_env_file=None)


@pytest.fixture
def state():
    s = ConversationState()
    s.add_customer("Price zyada hai yaar.")
    s.add_agent("Haan, samajh sakta hoon. Mahine mein kitni leads miss hoti hain?")
    s.add_customer("Theek hai, demo book kar do.")
    s.add_agent("Perfect, main slot bhej deta hoon.")
    return s


def evaluator(llm, settings) -> ConversationEvaluator:
    return ConversationEvaluator(llm, settings, judge_model="judge-test")


def test_structured_output_is_parsed(settings, state):
    result = evaluator(RecordingLLM([json.dumps(GOOD)]), settings).evaluate(
        get_scenario("price-expensive"), state
    )
    assert result.goal_completion_score == 2
    assert result.objection_handling_score == 3
    assert result.conversation_quality_score == 5
    assert result.overall_score == 5.0
    assert result.goal_completed is True
    assert "acknowledged" in result.reasoning
    assert set(result.as_json()) == {
        "goal_completion_score",
        "objection_handling_score",
        "conversation_quality_score",
        "overall_score",
        "reasoning",
    }


def test_fenced_json_is_accepted():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! {"a": 1} Hope that helps.') == {"a": 1}


@pytest.mark.parametrize("bad", ["", "no json here", "[1, 2]", "{broken"])
def test_unparseable_output_raises(bad):
    with pytest.raises(LLMResponseError):
        parse_json_object(bad)


def test_overall_score_is_computed_by_code_not_the_model(settings, state):
    reply = {**GOOD, "overall_score": 1.0, "goal_completion_score": 1}
    result = evaluator(RecordingLLM([json.dumps(reply)]), settings).evaluate(
        get_scenario("price-expensive"), state
    )
    assert result.overall_score == compute_overall(1, 3, 5)
    assert result.overall_score != 1.0


@pytest.mark.parametrize(
    "goal,objection,quality,expected",
    [
        (2, 3, 5, 5.0),
        (0, 0, 1, 0.3),
        (1, 2, 3, 2.9),
        (2, None, 5, 5.0),  # objection N/A: weights renormalised
        (0, None, 5, 2.14),
    ],
)
def test_compute_overall(goal, objection, quality, expected):
    assert compute_overall(goal, objection, quality) == pytest.approx(expected, abs=0.01)


def test_objection_can_be_not_applicable(settings, state):
    reply = {**GOOD, "objection_handling_score": None}
    result = evaluator(RecordingLLM([json.dumps(reply)]), settings).evaluate(
        get_scenario("intent-demo"), state
    )
    assert result.objection_handling_score is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("goal_completion_score", 3),
        ("objection_handling_score", 4),
        ("conversation_quality_score", 0),
        ("conversation_quality_score", 6),
        ("reasoning", ""),
    ],
)
def test_out_of_range_scores_are_rejected(settings, state, field, value):
    llm = RecordingLLM([json.dumps({**GOOD, field: value})])
    with pytest.raises(LLMResponseError):
        evaluator(llm, settings).evaluate(get_scenario("price-expensive"), state)
    assert len(llm.requests) == 2  # one retry before giving up


def test_malformed_then_valid_output_recovers(settings, state):
    llm = RecordingLLM(["oops", json.dumps(GOOD)])
    result = evaluator(llm, settings).evaluate(get_scenario("price-expensive"), state)
    assert result.overall_score == 5.0


def test_judge_is_blind_to_prompt_strategy(settings, state):
    llm = RecordingLLM([json.dumps(GOOD)])
    evaluator(llm, settings).evaluate(get_scenario("price-expensive"), state)
    request = llm.requests[0]
    haystack = (request.system + " " + request.messages[0].content).lower()
    for word in ("zero_shot", "zero-shot", "few-shot", "few_shot", "persona", "prompt variant"):
        assert word not in haystack
    assert request.model == "judge-test"
    assert request.task == "judge"


def test_same_rubric_for_every_scenario():
    a = build_judge_prompt(get_scenario("price-expensive"))
    b = build_judge_prompt(get_scenario("diff-one-word"))
    rubric_a = a[a.index("SCORING RUBRIC") : a.index("OUTPUT FORMAT")]
    rubric_b = b[b.index("SCORING RUBRIC") : b.index("OUTPUT FORMAT")]
    assert rubric_a == rubric_b


def test_mock_judge_end_to_end_produces_valid_scores(settings, state):
    result = evaluator(MockLLMProvider(), settings).evaluate(get_scenario("price-expensive"), state)
    assert 0 <= result.goal_completion_score <= 2
    assert 1 <= result.conversation_quality_score <= 5
    assert "MOCK" in result.reasoning
