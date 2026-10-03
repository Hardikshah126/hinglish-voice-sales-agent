"""Rough sizing of a benchmark run, so it can be compared with free-tier quotas up front.

This is an ESTIMATE: tokens are approximated as characters / 4 and conversation length is
assumed. Real usage appears in the provider's usage dashboard.
"""

from collections import defaultdict
from dataclasses import dataclass

from app.agent.simulator import build_simulator_prompt
from app.benchmark.runner import BenchmarkConfig, select_scenarios
from app.config import Settings
from app.evaluation.evaluator import build_judge_prompt
from app.prompts.registry import get_system_prompt

ASSUMED_EXCHANGES = 5  # typical conversation length before the customer agrees
TOKENS_PER_MESSAGE = 60
AGENT_OUTPUT_TOKENS = 70
SIMULATOR_OUTPUT_TOKENS = 50
JUDGE_OUTPUT_TOKENS = 150
JUDGE_REASONING_TOKENS = 700  # rough extra output tokens per reasoning-model call


@dataclass
class ModelLoad:
    requests: int = 0
    tokens: int = 0


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _reasoning(model: str) -> int:
    """gpt-oss models always reason; their reasoning tokens count as output tokens."""
    return JUDGE_REASONING_TOKENS if model.startswith("openai/gpt-oss") else 0


def estimate_load(config: BenchmarkConfig, settings: Settings) -> dict[str, ModelLoad]:
    exchanges = min(config.max_turns, ASSUMED_EXCHANGES)
    load: dict[str, ModelLoad] = defaultdict(ModelLoad)

    for scenario in select_scenarios(config):
        sim_sys = _tokens(build_simulator_prompt(scenario))
        judge_sys = _tokens(build_judge_prompt(scenario))
        for variant in config.variants:
            agent_sys = _tokens(get_system_prompt(variant))
            agent = load[settings.llm_model]
            for t in range(1, exchanges + 1):
                agent.requests += 1
                agent.tokens += (
                    agent_sys
                    + TOKENS_PER_MESSAGE * (2 * t - 1)
                    + AGENT_OUTPUT_TOKENS
                    + _reasoning(settings.llm_model)
                )
            sim = load[settings.simulator_model]
            for t in range(1, exchanges):
                sim.requests += 1
                sim.tokens += (
                    sim_sys
                    + TOKENS_PER_MESSAGE * 2 * t
                    + SIMULATOR_OUTPUT_TOKENS
                    + _reasoning(settings.simulator_model)
                )
            judge = load[settings.judge_model]
            judge.requests += 1
            judge.tokens += (
                judge_sys
                + TOKENS_PER_MESSAGE * 2 * exchanges
                + JUDGE_OUTPUT_TOKENS
                + _reasoning(settings.judge_model)
            )
    return dict(load)
