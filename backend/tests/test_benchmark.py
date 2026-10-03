import pytest
from sqlalchemy import func, select

from app.benchmark.report import generate_report
from app.benchmark.runner import BenchmarkConfig, create_run, execute_run
from app.config import Settings
from app.db.models import BenchmarkRun, Conversation, Evaluation, LatencyMetric, Turn
from app.db.session import get_sessionmaker
from app.domain import PromptVariant, RunStatus
from app.scenarios.loader import get_scenario

SCENARIOS = ("disc-excel", "price-expensive")


@pytest.fixture
def settings():
    return Settings(_env_file=None)


def run(providers, settings, **kwargs):
    factory = get_sessionmaker()
    config = BenchmarkConfig(scenario_ids=SCENARIOS, **kwargs)
    run_id = create_run(factory, providers, config)
    return run_id, execute_run(factory, providers, settings, run_id)


def test_full_matrix_is_run_and_evaluated(db, providers, settings):
    run_id, status = run(providers, settings)
    assert status == RunStatus.COMPLETED
    convs = db.scalars(select(Conversation).where(Conversation.benchmark_run_id == run_id)).all()
    assert len(convs) == len(SCENARIOS) * 3
    assert {(c.scenario_id, c.prompt_variant) for c in convs} == {
        (s, v.value) for s in SCENARIOS for v in PromptVariant
    }
    assert db.scalar(select(func.count()).select_from(Evaluation)) == len(convs)
    assert all(c.goal_completed is not None and c.completed_at for c in convs)
    assert all(c.run_mode == "mock" and c.source == "benchmark" for c in convs)


def test_run_metadata_counts(db, providers, settings):
    run_id, _ = run(providers, settings)
    row = db.get(BenchmarkRun, run_id)
    assert (row.total_conversations, row.completed_conversations, row.failed_conversations) == (
        6,
        6,
        0,
    )
    assert row.run_mode == "mock" and row.completed_at is not None


def test_same_scenario_opens_identically_across_strategies(db, providers, settings):
    run_id, _ = run(providers, settings)
    for sid in SCENARIOS:
        openers = {
            db.scalar(
                select(Turn.text)
                .join(Conversation)
                .where(
                    Conversation.benchmark_run_id == run_id,
                    Conversation.scenario_id == sid,
                    Conversation.prompt_variant == v.value,
                    Turn.speaker == "customer",
                    Turn.turn_number == 1,
                )
            )
            for v in PromptVariant
        }
        assert openers == {get_scenario(sid).initial_message}


def test_conversations_respect_max_turns_and_stop_reason(db, providers, settings):
    run_id, _ = run(providers, settings, max_turns=3)
    convs = db.scalars(select(Conversation).where(Conversation.benchmark_run_id == run_id)).all()
    for c in convs:
        agent_turns = db.scalar(
            select(func.count())
            .select_from(Turn)
            .where(Turn.conversation_id == c.id, Turn.speaker == "agent")
        )
        assert 1 <= agent_turns <= 3
        assert c.stop_reason in {"goal_reached", "max_turns", "customer_left"}


def test_benchmark_latency_is_measured_without_stt(db, providers, settings):
    run_id, _ = run(providers, settings)
    metrics = db.scalars(
        select(LatencyMetric).join(Conversation).where(Conversation.benchmark_run_id == run_id)
    ).all()
    assert metrics
    for m in metrics:
        assert m.source == "benchmark"
        assert m.stt_latency_ms is None
        assert m.llm_latency_ms >= 0 and m.tts_latency_ms >= 0
        assert m.total_latency_ms >= m.llm_latency_ms  # outer timer wraps the stages


def test_tts_can_be_excluded(db, providers, settings):
    run_id, _ = run(providers, settings, include_tts=False)
    metrics = db.scalars(
        select(LatencyMetric).join(Conversation).where(Conversation.benchmark_run_id == run_id)
    ).all()
    assert all(m.tts_latency_ms is None for m in metrics)


def test_resume_only_runs_missing_cells(db, providers, settings):
    factory = get_sessionmaker()
    run_id, _ = run(providers, settings)
    victim = db.scalars(select(Conversation).where(Conversation.benchmark_run_id == run_id)).first()
    db.delete(victim)
    db.query(BenchmarkRun).filter_by(id=run_id).update({"completed_conversations": 5})
    db.commit()

    status = execute_run(factory, providers, settings, run_id)
    assert status == RunStatus.COMPLETED
    assert (
        db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.benchmark_run_id == run_id)
        )
        == 6
    )


def test_failed_conversations_are_counted_not_fabricated(db, providers, settings):
    from tests.helpers import TimeoutLLM, with_providers

    broken = with_providers(providers, llm=TimeoutLLM())
    factory = get_sessionmaker()
    config = BenchmarkConfig(scenario_ids=("disc-excel",))
    run_id = create_run(factory, broken, config)
    status = execute_run(factory, broken, settings, run_id)
    row = db.get(BenchmarkRun, run_id)
    assert status == RunStatus.FAILED
    assert row.failed_conversations == 3 and row.completed_conversations == 0
    assert "timed out" in row.error
    assert db.scalar(select(func.count()).select_from(Conversation)) == 0


def test_report_labels_mock_results(db, providers, settings):
    run(providers, settings)
    report = generate_report(db)
    assert "MOCK RESULTS" in report
    assert "not representative of production model performance" in report
    for heading in (
        "## Dataset",
        "## Methodology",
        "## Latency",
        "## Failure Cases",
        "## Limitations",
    ):
        assert heading in report


def test_report_without_benchmark_says_not_run(db):
    assert "Benchmark not yet run" in generate_report(db)


def test_runs_left_running_by_a_dead_process_are_marked_failed(db, providers):
    from app.benchmark.runner import mark_interrupted_runs

    run_id = create_run(get_sessionmaker(), providers, BenchmarkConfig(scenario_ids=SCENARIOS))
    assert mark_interrupted_runs(get_sessionmaker()) == 1
    db.expire_all()
    row = db.get(BenchmarkRun, run_id)
    assert row.status == "failed" and "restart" in row.error


def test_quota_exhaustion_stops_cleanly_and_can_be_resumed(db, providers, settings):
    from tests.helpers import QuotaLLM, with_providers

    factory = get_sessionmaker()
    limited = with_providers(providers, llm=QuotaLLM(providers.llm, allow=25))
    config = BenchmarkConfig(scenario_ids=SCENARIOS)
    run_id = create_run(factory, limited, config)
    status = execute_run(factory, limited, settings, run_id)

    row = db.get(BenchmarkRun, run_id)
    assert status == RunStatus.PARTIAL
    assert 0 < row.completed_conversations < row.total_conversations
    assert row.failed_conversations == 0  # an exhausted quota is not a conversation failure
    assert "Resume later" in row.error
    db.expire_all()
    completed_before = row.completed_conversations

    # Next day the quota has reset: resume finishes only the missing cells.
    assert execute_run(factory, providers, settings, run_id) == RunStatus.COMPLETED
    db.expire_all()
    row = db.get(BenchmarkRun, run_id)
    assert row.completed_conversations == row.total_conversations == 6
    assert completed_before < 6


def test_resume_refuses_to_mix_models(db, providers, settings):
    from dataclasses import replace

    factory = get_sessionmaker()
    run_id = create_run(factory, providers, BenchmarkConfig(scenario_ids=SCENARIOS))
    other_model = replace(providers, llm_model="a-different-model")
    with pytest.raises(ValueError, match="differ"):
        execute_run(factory, other_model, settings, run_id)


def test_run_records_the_models_it_used(db, providers, settings):
    run_id, _ = run(providers, settings)
    assert db.get(BenchmarkRun, run_id).config["models"] == providers.llm_models


def test_client_side_tts_is_not_timed_in_benchmarks(db, providers, settings):
    from app.providers.openai_providers import BrowserTTSProvider
    from tests.helpers import with_providers

    run_id, _ = run(with_providers(providers, tts=BrowserTTSProvider()), settings)
    metrics = db.scalars(
        select(LatencyMetric).join(Conversation).where(Conversation.benchmark_run_id == run_id)
    ).all()
    assert metrics and all(m.tts_latency_ms is None for m in metrics)
