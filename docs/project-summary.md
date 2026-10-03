# Project Summary: Hinglish Voice Sales Agent

## One-line description

A voice AI sales agent that sells a fictional CRM in natural Hinglish, plus an evaluation harness that compares zero-shot, few-shot and persona prompting on 25 controlled scenarios and stores every conversation, score and latency measurement in PostgreSQL.

## Technical highlights

- **Experiment design, not just a chatbot.** Three prompt strategies share a byte-identical base brief and differ only in their added layer. A customer simulator that never sees the strategy plays every scenario; a blind LLM judge applies one fixed rubric. Seed, temperatures and turn limit are held constant.
- **Provider abstraction, zero cost.** `STTProvider` / `LLMProvider` / `TTSProvider` interfaces with Groq (free LLM + Whisper STT), browser speech synthesis (free TTS), optional OpenAI, and mock implementations, selected per component. Model names are configuration only. The entire system runs and is tested without any API key.
- **Preflight model verification.** `verify-models` lists each provider's models, smoke-tests them with the benchmark's exact parameters and reads account rate limits; real runs are blocked if it fails, and runs record (and refuse to mix) their models.
- **Free-tier engineering.** Own retry loop so rate-limit waits never count as latency; long `retry-after` is treated as an exhausted quota and the run stops as `partial` and resumes later; separate simulator/judge models use separate quota pools; judge is a different family from the agent.
- **Honest measurement.** Latency uses `time.perf_counter()` inside each provider call. Real voice latency (STT + LLM + TTS, `source='voice'`) is stored separately from simulated benchmark latency (`source='benchmark'`, text input, no STT). Mock-provider runs are tagged `run_mode='mock'` in the schema and labelled in the API, UI and report.
- **Validated structured evaluation.** Judge output is parsed into a Pydantic model with range checks, retried once on malformed output, and the overall score is computed in code (weighted, with objection handling dropped when no objection occurred).
- **PostgreSQL done properly.** Alembic migrations, CHECK constraints for score ranges / enums / non-negative latency, foreign keys with cascade rules, indexes, three analytics views, and 17 documented queries (percentiles with `percentile_cont`, `FILTER` pivots, histograms). Tests build the schema through the migrations and execute every query.
- **Robust voice endpoint.** Magic-byte audio sniffing, size limits, STT / LLM / TTS failure handling (TTS degrades to a text-only reply), timeouts, typed error envelope with request ids, JSON logs with secret redaction, path-traversal-safe audio serving, swappable audio storage interface.
- **Benchmark runner.** Paired scenario x strategy cells interleaved so partial runs stay comparable, atomic persistence per conversation, failure accounting, resume support, single-run guard for the API, cleanup of runs interrupted by a restart.
- **Frontend.** Next.js + TypeScript + Tailwind: hold-to-speak recorder, live latency card, dashboard with grouped bars, distributions, scenario heatmap and conversation explorer deep-linked from heatmap cells; mock-mode banner everywhere results could be mistaken for real.

## Architecture

```
Mic -> MediaRecorder -> POST /api/voice/respond
        -> audio validation -> STTProvider -> conversation state (PostgreSQL)
        -> prompt registry (zero | few | persona) -> LLMProvider -> TTSProvider
        -> audio file (local storage) + turns + latency_metrics rows

Benchmark: scenarios.json -> Customer simulator <-> Sales agent (strategy under test)
        -> transcript -> Judge (fixed rubric, blind) -> evaluations
        -> conversation_results view -> /api/evaluations/summary, SQL, report
```

See the Mermaid diagrams in the [README](../README.md).

## Evaluation methodology

- 25 scenarios in 7 categories (discovery, price objections, existing solutions, trust, timing, buying intent, difficult customers), difficulty 1-5; each with profile, opening message, goal, completion criteria and expected objection.
- Each scenario is run once per strategy: 25 x 3 = 75 conversations, max 8 turns, early stop when the simulated customer agrees to the goal or walks away.
- Rubric: goal completion 0-2, objection handling 0-3 (or N/A), conversation quality 1-5, invented-claims flag. Overall = 5 x (0.4 goal + 0.3 objection + 0.3 quality, normalised).
- Reported with per-strategy means, per-category / difficulty / scenario breakdowns, paired win/tie/loss counts, failure cases, standard errors and an explicit limitations list.

## Metrics (what has actually been measured)

| Item | Value |
|---|---|
| Scenarios / strategies / conversations per full run | 25 / 3 / 75 |
| Automated tests | 172 passing (pytest, real PostgreSQL) |
| SQL analytics queries | 17, all executed in tests and against PostgreSQL 16 |
| Mock-provider benchmark | 75/75 conversations completed and evaluated; **pipeline verification only** |
| Real-model benchmark | **Not run** (no API key was available during the build). Model names verified against provider docs only; live verification pending (`verify-models`) |

No claim is made about which prompt strategy is better. That requires running the benchmark with real providers; the tooling for it is complete (`python -m app.cli benchmark`).

## Resume bullets

Pick the three that fit the role; update the bracketed result after the real run.

1. **GenAI / experimentation.** Built a controlled prompt-evaluation framework comparing zero-shot, few-shot and persona strategies for a Hinglish sales agent: 25 scenarios x 3 strategies, a strategy-blind customer simulator and LLM judge with a fixed 3-dimension rubric, validated structured outputs, and automated report generation. [Optionally add after a real run: "Persona/few-shot/zero-shot scored X / Y / Z overall (n=25 per arm)."]
2. **Voice AI.** Built an end-to-end voice pipeline (browser mic -> STT -> stateful LLM agent -> TTS) behind swappable provider interfaces, with per-stage monotonic latency instrumentation that separates real voice latency from simulated benchmark latency, graceful degradation (text-only fallback on TTS failure) and audio validation.
3. **Backend / PostgreSQL.** Designed a PostgreSQL schema with Alembic migrations, CHECK/FK constraints, analytics views and 17 SQL queries (percentiles, FILTER pivots, histograms), served through a FastAPI backend with typed errors, structured logging and a 172-test suite that runs the migrations and every query against a real database; shipped a Next.js dashboard and conversation explorer on top.

## Interview talking points

- **Why the experiment is controlled.** Base prompt identical across arms (tested), same simulator / seed / temperature, judge blind to strategy, overall score computed in code. Be ready to discuss what is still uncontrolled: simulator stochasticity, judge self-preference, n=25.
- **Mock vs real honesty.** The system runs without credentials for testing, but mock results are tagged in the schema (`run_mode`) and labelled in the UI and report so they can never pass as model results. Mention that you caught and fixed a false positive in the mock judge (denials like "permanent free plan nahi hai" were flagged as invented claims).
- **Latency measurement design.** Why STT is absent from benchmark latency, why real and simulated numbers live in different `source` values, and why P95 matters more than the mean for voice.
- **Engineering tradeoffs.** Sync SQLAlchemy and threads instead of async for simplicity; conversations persisted atomically after evaluation so the DB never holds half-run benchmarks; one background benchmark at a time; local audio storage behind an interface for S3/R2 later.
- **What you would do next.** Multiple simulator seeds, a different-family judge, a human-labelled calibration set, and streaming STT/LLM/TTS to cut perceived latency.
