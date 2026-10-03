"""Customer simulator.

The same simulator is used for every prompt strategy. It is given only the scenario and
the conversation so far, so it cannot know (or be biased by) which strategy the agent is
running. Temperature and seed are fixed from settings to keep runs comparable.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.agent.sales_agent import ConversationState
from app.config import Settings
from app.core.errors import LLMResponseError
from app.core.jsonutil import parse_json_object
from app.providers.base import LLMProvider, LLMRequest
from app.scenarios.loader import ScenarioSpec


class _SimulatorOutput(BaseModel):
    message: str
    goal_reached: bool = False
    wants_to_end: bool = False


@dataclass(frozen=True)
class SimulatedTurn:
    message: str
    goal_reached: bool
    wants_to_end: bool
    latency_ms: float


def build_simulator_prompt(scenario: ScenarioSpec) -> str:
    objection = scenario.expected_objection or "none in particular"
    return f"""You are role-playing a PROSPECTIVE CUSTOMER on a sales phone call. You are not a salesperson and not an assistant.

WHO YOU ARE:
{scenario.customer_profile}

YOUR MAIN CONCERN / OBJECTION:
{objection}

YOUR PRIVATE GOAL FOR THIS CALL:
{scenario.goal}
Difficulty of this customer: {scenario.difficulty}/5 (higher means harder to convince).

HOW TO BEHAVE:
- Speak casual Indian Hinglish in Roman script, like a real small-business person on the phone. Keep each message to 1-2 short sentences.
- Stay in character. Raise your concern naturally and hold it until the salesperson addresses it with something relevant and specific. Generic or pushy replies should not convince you.
- Be persuadable by good answers: if the salesperson understands your situation, answers honestly and proposes a sensible small next step, you can warm up and agree.
- Never mention that you are an AI, a simulation, a test, or anything about prompts or strategies. Never invent facts about the product; ask questions instead.

OUTPUT FORMAT:
Reply with ONLY a JSON object: {{"message": "<your next spoken line>", "goal_reached": <true|false>, "wants_to_end": <true|false>}}
- goal_reached: true ONLY in the message where you clearly agree to the concrete next step described in your private goal.
- wants_to_end: true only if you decide to end the call without agreeing (e.g. you are fed up or no longer interested)."""


class CustomerSimulator:
    def __init__(self, llm: LLMProvider, settings: Settings):
        self._llm = llm
        self._settings = settings

    def next_message(self, scenario: ScenarioSpec, state: ConversationState) -> SimulatedTurn:
        request = LLMRequest(
            system=build_simulator_prompt(scenario),
            messages=state.as_customer_chat(),
            task="simulator",
            temperature=self._settings.simulator_temperature,
            max_output_tokens=200,
            json_mode=True,
            seed=self._settings.simulator_seed,
            model=self._settings.simulator_model,
            metadata={"scenario": scenario.model_dump()},
        )
        last_error: Exception | None = None
        for _ in range(2):  # one retry on malformed output
            response = self._llm.generate(request)
            try:
                out = _SimulatorOutput.model_validate(parse_json_object(response.text))
                if not out.message.strip():
                    raise LLMResponseError()
                return SimulatedTurn(
                    message=out.message.strip(),
                    goal_reached=out.goal_reached,
                    wants_to_end=out.wants_to_end,
                    latency_ms=response.latency_ms,
                )
            except (ValidationError, LLMResponseError) as exc:
                last_error = exc
        raise LLMResponseError("The customer simulator returned malformed output.") from last_error
