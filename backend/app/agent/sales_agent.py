"""The sales agent: conversation state plus a prompt-strategy-driven LLM call."""

import re
from dataclasses import dataclass, field

from app.config import Settings
from app.domain import PromptVariant, Speaker
from app.prompts.registry import PERSONA_NAME, get_system_prompt, prompt_hash
from app.providers.base import ChatMessage, LLMProvider, LLMRequest


@dataclass(frozen=True)
class Message:
    speaker: Speaker
    text: str


@dataclass
class ConversationState:
    """Ordered customer/agent messages. The single source of truth for conversation history."""

    messages: list[Message] = field(default_factory=list)

    def add_customer(self, text: str) -> None:
        self.messages.append(Message(Speaker.CUSTOMER, text))

    def add_agent(self, text: str) -> None:
        self.messages.append(Message(Speaker.AGENT, text))

    @property
    def customer_turns(self) -> int:
        return sum(m.speaker == Speaker.CUSTOMER for m in self.messages)

    def as_agent_chat(self) -> list[ChatMessage]:
        """History from the agent's point of view: customer = user, agent = assistant."""
        return [
            ChatMessage("user" if m.speaker == Speaker.CUSTOMER else "assistant", m.text)
            for m in self.messages
        ]

    def as_customer_chat(self) -> list[ChatMessage]:
        """History from the simulated customer's point of view (roles inverted)."""
        return [
            ChatMessage("assistant" if m.speaker == Speaker.CUSTOMER else "user", m.text)
            for m in self.messages
        ]

    def transcript(self) -> list[dict[str, str]]:
        return [{"speaker": m.speaker.value, "text": m.text} for m in self.messages]


@dataclass(frozen=True)
class AgentReply:
    text: str
    llm_latency_ms: float
    model: str


_SPEAKER_PREFIX = re.compile(rf"^\s*(agent|{PERSONA_NAME}|sales agent)\s*:\s*", re.I)


def clean_reply(text: str) -> str:
    """Strip role prefixes and wrapping quotes that models occasionally add."""
    text = _SPEAKER_PREFIX.sub("", text.strip())
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


class SalesAgent:
    def __init__(self, llm: LLMProvider, variant: PromptVariant, settings: Settings):
        self._llm = llm
        self._settings = settings
        self.variant = PromptVariant(variant)
        self.system_prompt = get_system_prompt(self.variant)
        self.prompt_hash = prompt_hash(self.system_prompt)

    def respond(self, state: ConversationState, customer_text: str) -> AgentReply:
        """Add the customer's message to the history, generate the reply, and record it."""
        state.add_customer(customer_text)
        response = self._llm.generate(
            LLMRequest(
                system=self.system_prompt,
                messages=state.as_agent_chat(),
                task="agent",
                temperature=self._settings.llm_temperature,
                max_output_tokens=self._settings.llm_max_output_tokens,
            )
        )
        text = clean_reply(response.text)
        state.add_agent(text)
        return AgentReply(text=text, llm_latency_ms=response.latency_ms, model=response.model)
