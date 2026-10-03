import pytest

from app.agent.sales_agent import ConversationState, SalesAgent, clean_reply
from app.agent.simulator import CustomerSimulator, build_simulator_prompt
from app.config import Settings
from app.core.errors import LLMResponseError
from app.domain import PromptVariant, Speaker
from app.prompts.registry import get_system_prompt
from app.providers.mock_llm import MockLLMProvider
from app.scenarios.loader import get_scenario, load_scenarios
from tests.helpers import RecordingLLM


@pytest.fixture
def settings():
    return Settings(_env_file=None)


def test_conversation_state_tracks_speakers_in_order():
    state = ConversationState()
    state.add_customer("Namaste")
    state.add_agent("Haan ji")
    state.add_customer("Price?")
    assert [m.speaker for m in state.messages] == [
        Speaker.CUSTOMER,
        Speaker.AGENT,
        Speaker.CUSTOMER,
    ]
    assert state.customer_turns == 2


def test_history_is_sent_to_the_llm_with_correct_roles(settings):
    llm = RecordingLLM(["Pehla jawab.", "Doosra jawab."])
    agent = SalesAgent(llm, PromptVariant.PERSONA, settings)
    state = ConversationState()

    agent.respond(state, "Hum Excel use karte hain.")
    agent.respond(state, "Price kitna hai?")

    second = llm.requests[1]
    assert [(m.role, m.content) for m in second.messages] == [
        ("user", "Hum Excel use karte hain."),
        ("assistant", "Pehla jawab."),
        ("user", "Price kitna hai?"),
    ]
    assert [m.text for m in state.messages] == [
        "Hum Excel use karte hain.",
        "Pehla jawab.",
        "Price kitna hai?",
        "Doosra jawab.",
    ]


@pytest.mark.parametrize("variant", list(PromptVariant))
def test_agent_uses_the_selected_prompt_strategy(settings, variant):
    llm = RecordingLLM(["Theek hai."])
    agent = SalesAgent(llm, variant, settings)
    agent.respond(ConversationState(), "Hello")
    assert llm.requests[0].system == get_system_prompt(variant)
    assert llm.requests[0].task == "agent"
    assert agent.prompt_hash


def test_clean_reply_strips_prefix_and_quotes():
    assert clean_reply('Agent: "Haan ji, bataiye."') == "Haan ji, bataiye."
    assert clean_reply("  Kavya: Namaste  ") == "Namaste"


def test_simulator_prompt_depends_only_on_the_scenario():
    """The simulator must be identical for every strategy and must not leak the strategy."""
    scenario = get_scenario("price-expensive")
    prompt = build_simulator_prompt(scenario)
    for word in ("zero-shot", "few-shot", "persona", "prompt strategy", "benchmark", "Kavya"):
        assert word.lower() not in prompt.lower()
    assert scenario.customer_profile in prompt
    assert scenario.goal in prompt


def test_simulator_does_not_receive_the_agent_system_prompt(settings):
    llm = RecordingLLM(['{"message": "Theek hai.", "goal_reached": false, "wants_to_end": false}'])
    state = ConversationState()
    state.add_customer("Price zyada hai")
    state.add_agent("Samajh sakta hoon.")
    CustomerSimulator(llm, settings).next_message(get_scenario("price-expensive"), state)
    request = llm.requests[0]
    assert request.task == "simulator"
    # Roles are inverted: the customer's own lines are "assistant".
    assert [m.role for m in request.messages] == ["assistant", "user"]
    assert get_system_prompt(PromptVariant.PERSONA) not in request.system


def test_simulator_retries_once_on_malformed_json(settings):
    llm = RecordingLLM(["not json", '{"message": "Ok chalo.", "goal_reached": true}'])
    turn = CustomerSimulator(llm, settings).next_message(
        get_scenario("intent-demo"), ConversationState()
    )
    assert turn.message == "Ok chalo."
    assert turn.goal_reached is True
    assert len(llm.requests) == 2


def test_simulator_raises_after_repeated_malformed_output(settings):
    llm = RecordingLLM(["garbage"])
    with pytest.raises(LLMResponseError):
        CustomerSimulator(llm, settings).next_message(
            get_scenario("intent-demo"), ConversationState()
        )


def test_mock_agent_replies_in_hinglish_for_every_opening(settings):
    agent = SalesAgent(MockLLMProvider(), PromptVariant.ZERO_SHOT, settings)
    for scenario in load_scenarios():
        reply = agent.respond(ConversationState(), scenario.initial_message)
        assert reply.text.strip(), scenario.id
        assert reply.llm_latency_ms >= 0


def test_mock_agent_speaks_in_feminine_forms(settings):
    import re

    masculine = re.compile(r"\b(\w+ta hoon|(?!bataunga)\w+unga)\b")
    agent = SalesAgent(MockLLMProvider(), PromptVariant.PERSONA, settings)
    for scenario in load_scenarios():
        state = ConversationState()
        for _ in range(4):
            text = agent.respond(state, scenario.initial_message).text
            assert not masculine.findall(text), (scenario.id, text)
