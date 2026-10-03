"""Command line entry point.

python -m app.cli seed                          sync scenarios into PostgreSQL
python -m app.cli verify-models [--no-smoke]    check configured models against the live APIs
python -m app.cli benchmark [--mock] [...]      run the benchmark (verifies models first)
python -m app.cli report [--run-id ID]          write reports/benchmark_report.md
"""

import argparse
import sys
import uuid

from app.benchmark.estimate import estimate_load
from app.benchmark.report import generate_report
from app.benchmark.runner import BenchmarkConfig, create_run, execute_run, filter_variants
from app.config import REPO_ROOT, Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.providers.factory import ProviderBundle, build_bundle, mock_bundle
from app.providers.model_check import ModelVerificationError, ensure_verified, verify_models
from app.scenarios.loader import seed_scenarios

REPORT_PATH = REPO_ROOT / "reports" / "benchmark_report.md"


def cmd_seed(_: argparse.Namespace) -> int:
    with get_sessionmaker()() as db:
        count = seed_scenarios(db)
        db.commit()
    print(f"Seeded {count} scenarios.")
    return 0


def _print_estimate(config: BenchmarkConfig, settings: Settings) -> None:
    print("\nRough size of this run (estimate: ~chars/4 tokens, ~5 turns per conversation):")
    for model, load in estimate_load(config, settings).items():
        print(f"  {model:<28} ~{load.requests:>5} requests  ~{load.tokens:>9,} tokens")
    print("Compare with your daily limits at https://console.groq.com/settings/limits;")
    print("if they are lower, the run stops cleanly when a quota is hit. Re-run with --resume.")


def _print_report(report) -> None:
    print(f"{'component':<10} {'provider':<8} {'model':<30} {'status':<8} detail")
    for c in report.checks:
        print(f"{c.component:<10} {c.provider:<8} {c.model:<30} {c.status:<8} {c.detail}")
    for lim in report.limits:
        print(
            f"\nrate limits for {lim.model}: {lim.requests_limit or '?'} requests/day, "
            f"{lim.tokens_limit or '?'} tokens/min "
            f"(remaining now: {lim.requests_remaining or '?'} req, {lim.tokens_remaining or '?'} tok)"
        )


def cmd_verify_models(args: argparse.Namespace) -> int:
    settings = get_settings()
    bundle = build_bundle(settings)
    report = verify_models(settings, bundle, smoke=not args.no_smoke)
    _print_report(report)
    if bundle.llm.is_mock:
        print("\nNOT VERIFIED: no GROQ_API_KEY is configured, so the LLM is a mock and the real")
        print("model names could not be checked against Groq. Create a free key at")
        print("https://console.groq.com/keys, put it in .env, and run this command again.")
        return 2
    print("\nVERIFIED" if report.passed else "\nVERIFICATION FAILED")
    return 0 if report.passed else 1


def _bundle(args: argparse.Namespace, settings: Settings) -> ProviderBundle:
    return mock_bundle() if args.mock else build_bundle(settings)


def cmd_benchmark(args: argparse.Namespace) -> int:
    settings = get_settings()
    providers = _bundle(args, settings)
    factory = get_sessionmaker()
    config = BenchmarkConfig(
        variants=filter_variants(args.variants),
        scenario_ids=tuple(args.scenarios) if args.scenarios else None,
        include_tts=not args.no_tts and settings.benchmark_include_tts,
        max_turns=args.max_turns or settings.benchmark_max_turns,
        concurrency=args.concurrency or settings.benchmark_concurrency,
    )
    if not providers.llm.is_mock:
        if args.skip_model_check:
            print("WARNING: skipping model verification (--skip-model-check).")
        else:
            print("Verifying configured models against the live provider APIs...")
            try:
                _print_report(ensure_verified(settings, providers))
            except ModelVerificationError as exc:
                print(f"\n{exc.message}\nRun `python -m app.cli verify-models` for details.")
                return 2
        _print_estimate(config, settings)

    run_id = uuid.UUID(args.resume) if args.resume else create_run(factory, providers, config)
    label = "MOCK" if providers.llm.is_mock else "REAL"
    print(f"\nBenchmark run {run_id} [{label}] starting...")
    try:
        status = execute_run(factory, providers, settings, run_id)
    except (ValueError, AppError) as exc:
        print(f"Cannot run: {getattr(exc, 'message', exc)}")
        return 2
    print(f"Benchmark run {run_id} finished with status: {status.value}")
    if status.value == "partial":
        print(f"Some cells were not completed (quota or errors). Resume with: --resume {run_id}")
    return 0 if status.value == "completed" else 1


def cmd_report(args: argparse.Namespace) -> int:
    with get_sessionmaker()() as db:
        text = generate_report(
            db, run_id=uuid.UUID(args.run_id) if args.run_id else None, run_mode=args.mode
        )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="sync scenarios into the database").set_defaults(func=cmd_seed)

    v = sub.add_parser("verify-models", help="verify configured models against live provider APIs")
    v.add_argument("--no-smoke", action="store_true", help="only list models, skip test calls")
    v.set_defaults(func=cmd_verify_models)

    b = sub.add_parser("benchmark", help="run the prompt-strategy benchmark")
    b.add_argument("--mock", action="store_true", help="force mock providers (no API calls)")
    b.add_argument("--variants", nargs="+", choices=["zero_shot", "few_shot", "persona"])
    b.add_argument("--scenarios", nargs="+", help="scenario ids to run (default: all)")
    b.add_argument("--max-turns", type=int)
    b.add_argument("--concurrency", type=int)
    b.add_argument("--no-tts", action="store_true", help="skip TTS timing in benchmark turns")
    b.add_argument("--resume", metavar="RUN_ID", help="resume an interrupted or partial run")
    b.add_argument("--skip-model-check", action="store_true", help="do not verify models first")
    b.set_defaults(func=cmd_benchmark)

    r = sub.add_parser("report", help="generate reports/benchmark_report.md")
    r.add_argument("--run-id")
    r.add_argument("--mode", choices=["mock", "real"])
    r.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    quiet = args.command in {"benchmark", "verify-models"}
    configure_logging("WARNING" if quiet else get_settings().log_level)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
