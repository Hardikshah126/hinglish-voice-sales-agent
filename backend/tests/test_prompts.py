import re

import pytest

from app.domain import PromptVariant
from app.product import FLOWDESK
from app.prompts.registry import (
    FEW_SHOT_EXAMPLES,
    PERSONA_NAME,
    PROMPT_REGISTRY,
    get_system_prompt,
    prompt_hash,
)


def test_exactly_three_variants_registered():
    assert set(PROMPT_REGISTRY) == {
        PromptVariant.ZERO_SHOT,
        PromptVariant.FEW_SHOT,
        PromptVariant.PERSONA,
    }


@pytest.mark.parametrize("variant", list(PromptVariant))
def test_every_prompt_contains_the_shared_product_brief(variant):
    prompt = get_system_prompt(variant)
    assert FLOWDESK.fact_sheet() in prompt
    assert "Hinglish" in prompt
    assert "Never invent" in prompt


def test_prompts_are_distinct_and_hash_differs():
    prompts = {v: get_system_prompt(v) for v in PromptVariant}
    assert len(set(prompts.values())) == 3
    assert len({prompt_hash(p) for p in prompts.values()}) == 3


def test_prompt_is_deterministic():
    assert get_system_prompt(PromptVariant.PERSONA) == get_system_prompt(PromptVariant.PERSONA)
    assert prompt_hash("abc") == prompt_hash("abc")


def test_zero_shot_has_no_examples_or_persona():
    prompt = get_system_prompt(PromptVariant.ZERO_SHOT)
    assert "Example 1" not in prompt
    assert PERSONA_NAME not in prompt


def test_few_shot_contains_five_required_examples():
    assert len(FEW_SHOT_EXAMPLES) == 5
    titles = " ".join(e.title.lower() for e in FEW_SHOT_EXAMPLES)
    for topic in ("price", "excel", "competitor", "think", "demo"):
        assert topic in titles
    prompt = get_system_prompt(PromptVariant.FEW_SHOT)
    for i in range(1, 6):
        assert f"Example {i}:" in prompt
    assert PERSONA_NAME not in prompt


def test_persona_is_rich_and_has_no_examples():
    prompt = get_system_prompt(PromptVariant.PERSONA)
    assert PERSONA_NAME in prompt
    assert "acknowledge" in prompt.lower()
    assert "Example 1" not in prompt
    assert len(prompt) > len(get_system_prompt(PromptVariant.ZERO_SHOT)) * 1.5


def test_strategies_only_differ_by_their_layer():
    """The controlled-experiment property: the zero-shot brief is a prefix of the others."""
    base = get_system_prompt(PromptVariant.ZERO_SHOT)
    assert get_system_prompt(PromptVariant.FEW_SHOT).startswith(base)
    assert get_system_prompt(PromptVariant.PERSONA).startswith(base)


def test_product_facts_come_from_central_config_only():
    prompt = get_system_prompt(PromptVariant.ZERO_SHOT)
    for plan in FLOWDESK.plans:
        assert str(plan.price_inr_per_user_month) in prompt


MASCULINE_FIRST_PERSON = re.compile(r"\b(\w+ta hoon|(?!bataunga)\w+unga)\b")


def test_persona_has_a_female_name_and_the_agent_speaks_as_a_woman():
    assert PERSONA_NAME == "Kavya"
    for variant in PromptVariant:
        prompt = get_system_prompt(variant)
        assert "You are a woman" in prompt  # shared by all strategies: keeps the comparison fair
        assert "Rahul" not in prompt


def test_prompts_use_feminine_first_person_forms_only():
    """Few-shot examples and persona text must not teach masculine Hindi self-reference."""
    for variant in PromptVariant:
        prompt = get_system_prompt(variant)
        # strip the one deliberate "never say these" sentence in the base brief
        prompt = (
            prompt.split("never masculine ones")[0]
            + prompt.split("never masculine ones")[1].split("\n", 1)[1]
        )
        assert not MASCULINE_FIRST_PERSON.findall(prompt), (
            variant,
            MASCULINE_FIRST_PERSON.findall(prompt),
        )
