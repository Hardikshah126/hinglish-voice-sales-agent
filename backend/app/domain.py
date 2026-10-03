"""Shared enums / constants used by the DB layer, API and agent code."""

from enum import StrEnum


class PromptVariant(StrEnum):
    ZERO_SHOT = "zero_shot"
    FEW_SHOT = "few_shot"
    PERSONA = "persona"


class Speaker(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"


class RunMode(StrEnum):
    """Whether the conversation was produced by real model providers or by mocks."""

    MOCK = "mock"
    REAL = "real"


class ConversationSource(StrEnum):
    VOICE = "voice"
    BENCHMARK = "benchmark"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class StopReason(StrEnum):
    GOAL_REACHED = "goal_reached"
    CUSTOMER_LEFT = "customer_left"
    MAX_TURNS = "max_turns"
    ERROR = "error"


SCENARIO_CATEGORIES = (
    "discovery",
    "price_objection",
    "existing_solution",
    "trust",
    "timing",
    "buying_intent",
    "difficult_customer",
)


def sql_in(values) -> str:
    """Render a SQL IN-list literal from trusted constant values (used in CHECK constraints)."""
    return ", ".join(f"'{v}'" for v in values)
