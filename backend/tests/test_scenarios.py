from sqlalchemy import func, select

from app.db.models import Scenario
from app.domain import SCENARIO_CATEGORIES
from app.scenarios.loader import get_scenario, load_scenarios, seed_scenarios


def test_25_scenarios_load():
    assert len(load_scenarios()) == 25


def test_ids_are_unique():
    ids = [s.id for s in load_scenarios()]
    assert len(ids) == len(set(ids))


def test_every_scenario_has_required_fields_and_criteria():
    for s in load_scenarios():
        assert s.completion_criteria, s.id
        assert all(c.strip() for c in s.completion_criteria)
        assert s.initial_message.strip()
        assert s.goal.strip()
        assert s.customer_profile.strip()
        assert 1 <= s.difficulty <= 5


def test_all_seven_categories_are_covered():
    assert {s.category for s in load_scenarios()} == set(SCENARIO_CATEGORIES)


def test_difficulty_spread():
    assert {s.difficulty for s in load_scenarios()} >= {1, 2, 3, 4, 5}


def test_required_scenarios_exist():
    for sid in (
        "disc-excel",
        "price-expensive",
        "price-free-version",
        "exist-salesforce",
        "trust-data-security",
        "timing-think",
        "intent-demo",
        "diff-one-word",
        "diff-unrelated",
    ):
        assert get_scenario(sid) is not None, sid


def test_seed_is_idempotent(db):
    assert seed_scenarios(db) == 25
    db.commit()
    assert seed_scenarios(db) == 25
    db.commit()
    assert db.scalar(select(func.count()).select_from(Scenario)) == 25


def test_seeded_rows_match_json(db):
    seed_scenarios(db)
    db.commit()
    row = db.get(Scenario, "disc-excel")
    assert row is not None
    assert row.initial_message == get_scenario("disc-excel").initial_message
    assert isinstance(row.completion_criteria, list)
