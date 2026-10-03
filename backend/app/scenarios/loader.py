"""Load the controlled benchmark scenarios and sync them into PostgreSQL."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Scenario
from app.domain import SCENARIO_CATEGORIES

SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")


class ScenarioSpec(BaseModel):
    id: str
    category: str
    name: str
    description: str
    customer_profile: str
    initial_message: str
    goal: str
    completion_criteria: list[str] = Field(min_length=1)
    expected_objection: str | None = None
    difficulty: int = Field(ge=1, le=5)

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        if v not in SCENARIO_CATEGORIES:
            raise ValueError(f"unknown category {v!r}")
        return v


@lru_cache
def load_scenarios() -> tuple[ScenarioSpec, ...]:
    raw = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    scenarios = tuple(ScenarioSpec.model_validate(item) for item in raw)
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scenario ids in scenarios.json")
    return scenarios


def get_scenario(scenario_id: str) -> ScenarioSpec | None:
    return next((s for s in load_scenarios() if s.id == scenario_id), None)


def seed_scenarios(session: Session) -> int:
    """Upsert every scenario from scenarios.json. Returns the number of scenarios synced."""
    scenarios = load_scenarios()
    for s in scenarios:
        values = s.model_dump()
        stmt = insert(Scenario).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Scenario.id],
            set_={k: v for k, v in values.items() if k != "id"},
        )
        session.execute(stmt)
    session.flush()
    return len(scenarios)
