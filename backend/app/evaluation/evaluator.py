"""LLM-as-judge conversation evaluator.

One rubric is applied identically to every conversation. The judge sees the scenario and
the transcript only. It is never told which prompt strategy produced the agent's replies.
The overall score is computed deterministically in code, not by the model.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from app.agent.sales_agent import ConversationState
from app.config import Settings
from app.core.errors import LLMResponseError
from app.core.jsonutil import parse_json_object
from app.product import FLOWDESK
from app.providers.base import ChatMessage, LLMProvider, LLMRequest
from app.scenarios.loader import ScenarioSpec

# Weights for the 0-5 overall score. Objection handling is dropped (and the remaining
# weights renormalised) when the customer never raised an objection.
WEIGHT_GOAL = 0.4
WEIGHT_OBJECTION = 0.3
WEIGHT_QUALITY = 0.3

RUBRIC = """SCORING RUBRIC (apply it exactly the same way to every conversation)

goal_completion_score (integer 0-2):
  0 = failed: the customer did not move toward the scenario goal.
  1 = partially achieved: some completion criteria met or the customer showed clear interest, but no firm commitment to the next step.
  2 = achieved: the completion criteria are satisfied and the customer clearly agreed to the next step.

objection_handling_score (integer 0-3, or null if the customer never actually raised an objection or concern):
  Judge the agent's response to the customer's objection on: acknowledgement, relevance, specificity, handling quality, and a useful follow-up.
  0 = ignored the objection.
  1 = weak: generic, dismissive or missing most of the five elements.
  2 = reasonable: acknowledged and relevant but not very specific, or missing the follow-up.
  3 = strong: acknowledged, relevant, specific to the customer's situation, resolved or advanced the concern, and ended with a useful follow-up.

conversation_quality_score (integer 1-5), considering together: naturalness, clarity, relevance, conversational flow, appropriate Hinglish (natural mix, not stiff English or forced Hindi), and non-pushy behaviour.
  1 = poor, 2 = below average, 3 = acceptable, 4 = good, 5 = excellent and indistinguishable from a skilled human salesperson.

invented_claims (boolean): true if the agent stated any capability, price, discount, integration, customer, statistic or certification that is NOT in the product facts, or claimed something the facts say FlowDesk does not do.

Be strict and consistent. Judge only what is in the transcript."""


class _JudgeOutput(BaseModel):
    goal_completion_score: int = Field(ge=0, le=2)
    objection_handling_score: int | None = Field(default=None, ge=0, le=3)
    conversation_quality_score: int = Field(ge=1, le=5)
    invented_claims: bool = False
    reasoning: str = Field(min_length=1)


@dataclass(frozen=True)
class EvaluationResult:
    goal_completion_score: int
    objection_handling_score: int | None
    conversation_quality_score: int
    overall_score: float
    invented_claims: bool
    reasoning: str
    judge_model: str

    @property
    def goal_completed(self) -> bool:
        return self.goal_completion_score == 2

    def as_json(self) -> dict:
        return {
            "goal_completion_score": self.goal_completion_score,
            "objection_handling_score": self.objection_handling_score,
            "conversation_quality_score": self.conversation_quality_score,
            "overall_score": self.overall_score,
            "reasoning": self.reasoning,
        }


def compute_overall(goal: int, objection: int | None, quality: int) -> float:
    """Weighted average of the normalised dimension scores, on a 0-5 scale."""
    parts = [(WEIGHT_GOAL, goal / 2), (WEIGHT_QUALITY, quality / 5)]
    if objection is not None:
        parts.append((WEIGHT_OBJECTION, objection / 3))
    total_weight = sum(w for w, _ in parts)
    return round(5 * sum(w * s for w, s in parts) / total_weight, 2)


def build_judge_prompt(scenario: ScenarioSpec) -> str:
    criteria = "\n".join(f"- {c}" for c in scenario.completion_criteria)
    objection = scenario.expected_objection or "none expected"
    return f"""You are an impartial evaluator of sales conversations between a salesperson (Agent) and a prospective customer (Customer) for the product FlowDesk.

PRODUCT FACTS (ground truth for checking claims):
{FLOWDESK.fact_sheet()}

SCENARIO: {scenario.name}
Customer goal for the call: {scenario.goal}
Completion criteria:
{criteria}
Expected objection: {objection}

{RUBRIC}

OUTPUT FORMAT:
Reply with ONLY a JSON object with exactly these keys:
{{"goal_completion_score": <0-2>, "objection_handling_score": <0-3 or null>, "conversation_quality_score": <1-5>, "invented_claims": <true|false>, "reasoning": "<2-4 sentences citing specific moments from the transcript>"}}"""


def format_transcript(state: ConversationState) -> str:
    return "\n".join(f"{m.speaker.value.capitalize()}: {m.text}" for m in state.messages)


class ConversationEvaluator:
    def __init__(self, llm: LLMProvider, settings: Settings, judge_model: str):
        self._llm = llm
        self._settings = settings
        self._judge_model = judge_model

    def evaluate(self, scenario: ScenarioSpec, state: ConversationState) -> EvaluationResult:
        request = LLMRequest(
            system=build_judge_prompt(scenario),
            messages=[
                ChatMessage("user", f"Transcript:\n\n{format_transcript(state)}\n\nEvaluate it.")
            ],
            task="judge",
            temperature=self._settings.judge_temperature,
            json_mode=True,
            model=self._judge_model,
            metadata={"scenario": scenario.model_dump(), "transcript": state.transcript()},
        )
        last_error: Exception | None = None
        for _ in range(2):  # one retry on malformed output
            response = self._llm.generate(request)
            try:
                out = _JudgeOutput.model_validate(parse_json_object(response.text))
            except (ValidationError, LLMResponseError) as exc:
                last_error = exc
                continue
            return EvaluationResult(
                goal_completion_score=out.goal_completion_score,
                objection_handling_score=out.objection_handling_score,
                conversation_quality_score=out.conversation_quality_score,
                overall_score=compute_overall(
                    out.goal_completion_score,
                    out.objection_handling_score,
                    out.conversation_quality_score,
                ),
                invented_claims=out.invented_claims,
                reasoning=out.reasoning.strip(),
                judge_model=response.model,
            )
        raise LLMResponseError("The evaluator returned malformed output.") from last_error
