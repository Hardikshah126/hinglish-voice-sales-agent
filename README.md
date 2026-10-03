# Hinglish Voice Sales Agent

A voice-based AI sales agent that sells a fictional CRM (FlowDesk) in natural Indian Hinglish, plus a harness that **systematically evaluates how zero-shot, few-shot and persona prompting change sales performance** on 25 controlled scenarios, with everything stored in PostgreSQL.

> **Runs for free.** All LLM calls (sales agent, customer simulator, judge) go through **Groq's free tier**, speech-to-text uses **Groq Whisper**, and speech output uses the **browser's built-in speech synthesis**. The only thing you need is a free `GROQ_API_KEY`. OpenAI STT/TTS are supported but optional (paid).
>
> **Status of the numbers in this repo.** The project was built without any API key, so every benchmark result currently in the database/report was produced by the built-in **mock providers** and is labelled `MOCK` everywhere (API, UI, report). Mock results verify the pipeline; they say nothing about how real models behave. The Groq model names were verified against the **live Groq API** on 2026-10-03 (`python -m app.cli verify-models`; see [`docs/model-verification.md`](docs/model-verification.md)). That check also showed that Groq's docs listed two Llama models the API does not actually serve, so the defaults use Qwen and gpt-oss. **No real benchmark has been run yet.**

## Demo

| Voice Agent | Evaluation dashboard | Conversation explorer |
|---|---|---|
| Hold-to-speak mic, transcript, strategy picker, live STT/LLM/TTS latency | Strategy comparison table, charts, scenario heatmap | Filterable transcripts with scores and per-turn latency |

2-5 minute walkthrough:

1. Open **Voice Agent**, choose **Persona**.
2. Hold the mic and say *"Hum abhi Excel pe leads manage karte hain."* (with mock providers, type the line or click a sample chip instead).
3. The agent replies in Hinglish and speaks it back; the **Latency** card shows STT / LLM / TTS / total for that real request.
4. Open **Evaluation**: zero-shot vs few-shot vs persona on goal completion, objection handling, quality and latency.
5. Scroll to the scenario heatmap, click a cell to open that conversation in the **Conversation explorer** and show its transcript, rubric scores and judge reasoning.
6. Run `psql -f sql/analysis.sql` to show the same numbers coming straight out of PostgreSQL.

## Why this project exists

Most "voice bot" demos stop at *it talks*. The interesting engineering question is **does the prompt strategy actually matter, and how would you know?** This repo treats prompt choice as an experiment: identical scenarios, an identical simulated customer, one fixed judge rubric, persisted results, and SQL to interrogate them.

## Features

- **Voice pipeline**: microphone -> Whisper STT (Groq, free) -> conversation state -> prompt strategy -> LLM (Groq, free) -> TTS (browser voice, free; OpenAI optional) -> spoken reply, with per-stage latency measured on a monotonic clock.
- **Three prompt strategies** behind a clean registry (`zero_shot`, `few_shot`, `persona`) that share one base brief so the comparison is controlled.
- **Customer simulator** that never learns which strategy it is talking to.
- **LLM-as-judge evaluator** returning validated structured JSON (goal 0-2, objection handling 0-3, quality 1-5, invented-claims flag); the overall score is computed in code.
- **Benchmark runner**: 25 scenarios x 3 strategies = 75 conversations, up to 8 turns, early stop on goal, resumable, one-at-a-time background execution via the API.
- **PostgreSQL** schema with constraints, indexes, Alembic migrations and analytics views.
- **17 documented SQL queries** (`sql/analysis.sql`) and a **Next.js dashboard** (charts, heatmap, explorer).
- **Provider abstraction** (`STTProvider` / `LLMProvider` / `TTSProvider`) with Groq, OpenAI, browser-TTS and mock implementations chosen per component, so the system runs, and is tested, without credentials.
- **Model preflight** (`python -m app.cli verify-models`): confirms every configured model exists on the live provider API, smoke-tests it with the exact parameters the benchmark uses, and reports your account's rate limits. A real benchmark refuses to start if it fails.
- **Free-tier friendly benchmark**: rate-limit waits are excluded from measured latency, an exhausted daily quota stops the run cleanly as `partial`, and `--resume` continues the next day.
- Safe error handling (bad/oversized audio, STT/LLM/TTS failures, timeouts, malformed model output), structured JSON logs, secret redaction.

## Prompt experiment

| Strategy | What is added on top of the shared base brief |
|---|---|
| **Zero-shot** | Nothing. Product facts, sales objective, language requirement, basic constraints. |
| **Few-shot** | Five worked Hinglish dialogues: price objection, Excel user, competitor user, "need to think", demo request. |
| **Persona** | "Kavya", a consultative SaaS sales consultant: voice and tone rules, a 5-step selling method, a 4-step objection method (acknowledge, understand, respond specifically, follow up) and per-objection guidance. No example dialogues. |

The base brief (FlowDesk fact sheet, objective, Hinglish requirement, "never invent / never pressure" constraints) is byte-identical across strategies (`tests/test_prompts.py` asserts the zero-shot prompt is a prefix of the other two). Product facts live only in `backend/app/product.py`.

## Evaluation methodology

```mermaid
flowchart LR
  S[Scenario<br/>profile, goal, criteria] --> SIM[Customer simulator<br/>same model, temp, seed]
  P[Prompt strategy<br/>zero / few / persona] --> AG[Sales agent]
  SIM <--> AG
  AG --> T[Transcript + per-turn latency]
  T --> J[Judge LLM<br/>fixed rubric, blind to strategy]
  J --> DB[(PostgreSQL)]
  T --> DB
  DB --> D[Dashboard / SQL / report]
```

- **Controlled**: the only thing that changes between the three conversations for a scenario is the agent's system prompt. Same opening customer message, same simulator prompt, temperature and seed.
- **Blind judge**: sees product facts, scenario goal/criteria and the transcript, never the strategy name.
- **Rubric**: goal completion 0-2; objection handling 0-3 (acknowledgement, relevance, specificity, handling quality, follow-up; `NULL` when no objection was raised); quality 1-5 (naturalness, clarity, relevance, flow, Hinglish, non-pushy); `invented_claims` flag checked against the FlowDesk fact sheet.
- **Overall (0-5)** = 5 x weighted mean of normalised scores (goal 0.4, objection 0.3, quality 0.3; objection weight dropped when N/A).
- **Latency**: *real voice latency* (live `/api/voice/respond`, `source='voice'`: STT + LLM + TTS) is stored separately from *simulated benchmark latency* (`source='benchmark'`: text input so no STT; LLM + optional TTS). They are never mixed.

## System architecture

```mermaid
flowchart TB
  subgraph Browser
    UI[Next.js UI<br/>Voice / Evaluation / Conversations]
  end
  subgraph API[FastAPI]
    V[/api/voice/respond/]
    C[/api/conversations/]
    E[/api/evaluations/]
    B[/api/benchmark/]
  end
  subgraph Core
    PIPE[Voice pipeline]
    AGENT[Sales agent + prompt registry]
    SIM[Customer simulator]
    EVAL[Evaluator]
    RUN[Benchmark runner]
  end
  subgraph Providers
    STT[STTProvider]
    LLM[LLMProvider]
    TTS[TTSProvider]
  end
  UI --> V & C & E & B
  V --> PIPE --> STT & AGENT & TTS
  AGENT --> LLM
  B --> RUN --> AGENT & SIM & EVAL
  SIM & EVAL --> LLM
  PIPE & RUN & E & C --> PG[(PostgreSQL)]
  PIPE --> AUD[(data/audio)]
  LLM -.-> GROQ[Groq<br/>qwen / gpt-oss]
  STT -.-> GROQ
  TTS -.-> BR[Browser speech synthesis]
  STT & TTS -.-> OAI[OpenAI optional]
  STT & LLM & TTS -.-> MOCK[Mock providers]
```

## Tech stack

Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, psycopg 3, httpx, pytest; Groq (OpenAI-compatible API) for LLM and STT, browser speech synthesis for TTS, optional OpenAI STT/TTS (model names are configuration, not code); Next.js 16 (App Router), TypeScript, Tailwind CSS 4, Recharts.

## Database schema

```mermaid
erDiagram
  scenarios ||--o{ conversations : "scenario_id"
  benchmark_runs ||--o{ conversations : "benchmark_run_id"
  conversations ||--o{ turns : has
  conversations ||--o| evaluations : scored_by
  conversations ||--o{ latency_metrics : has
  turns ||--o| latency_metrics : "agent turn"
  scenarios { text id PK
    text category
    jsonb completion_criteria
    smallint difficulty }
  conversations { uuid id PK
    text prompt_variant
    text run_mode "mock or real"
    text source "voice or benchmark"
    bool goal_completed }
  turns { bigint id PK
    int turn_number
    text speaker
    float latency_ms }
  evaluations { bigint id PK
    smallint goal_completion_score
    smallint objection_handling_score
    smallint conversation_quality_score
    numeric overall_score }
  latency_metrics { bigint id PK
    float stt_latency_ms
    float llm_latency_ms
    float tts_latency_ms
    float total_latency_ms }
```

Beyond the five required tables there is `benchmark_runs` (status, counts, config, mock/real) and three views used by analytics: `conversation_results`, `turn_latencies`, `latest_benchmark_run`. CHECK constraints enforce score ranges, enum values and non-negative latency; foreign keys cascade from conversations; scenarios are `RESTRICT`-protected.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + DB check + provider mode |
| POST | `/api/conversations` | Create a conversation (`prompt_variant`, optional `scenario_id`) |
| GET | `/api/conversations` | List with filters: variant, scenario, category, goal, score range, run mode, source |
| GET | `/api/conversations/{id}` | Transcript, scenario, evaluation, per-turn latency |
| POST | `/api/voice/respond` | multipart `audio` + `prompt_variant` (+ `conversation_id`) -> transcript, reply, `audio_url`, latency |
| GET | `/api/evaluations` | Evaluation rows (same filters) |
| GET | `/api/evaluations/summary` | Aggregates for the dashboard (by strategy / category / difficulty, matrix, distributions) |
| GET | `/api/benchmark` | Run status and history |
| POST | `/api/benchmark/run` | Start a background run (409 if one is already running) |
| GET | `/api/config`, `/api/scenarios`, `/api/audio/{key}` | UI support |

Interactive docs: `http://localhost:8000/docs`. Errors are always `{"error": {"code", "message", "request_id"}}`; stack traces never reach clients.

`POST /api/voice/respond` response (numbers are placeholders; with browser TTS `audio_url` is null and the browser speaks `response_text`; with OpenAI TTS `audio_url` points at the generated mp3):

```json
{
  "conversation_id": "…",
  "transcript": "Hum abhi Excel pe leads manage karte hain.",
  "response_text": "Haan, kaafi businesses shuru mein Excel se hi chalate hain. …",
  "audio_url": null,
  "speak_client_side": true,
  "latency": {"stt_ms": 0, "llm_ms": 0, "tts_ms": null, "total_ms": 0},
  "warnings": [],
  "mock_mode": false,
  "mock_components": []
}
```

## Benchmark

25 scenarios in `backend/app/scenarios/scenarios.json` across 7 categories (discovery 3, price objections 4, existing solutions 4, trust 3, timing 3, buying intent 4, difficult customers 4), difficulty 1-5. Each has `id, category, name, customer_profile, initial_message, goal, completion_criteria[], expected_objection, difficulty`.

```bash
cd backend
python -m app.cli benchmark            # real if OPENAI_API_KEY is set, else mock (labelled)
python -m app.cli benchmark --mock     # force mock providers
python -m app.cli benchmark --scenarios disc-excel price-expensive --variants persona
python -m app.cli benchmark --resume <run-id>
python -m app.cli report               # writes reports/benchmark_report.md
```

A run stops each conversation after 8 turns or as soon as the simulated customer clearly agrees to the goal or walks away. Conversations are persisted atomically only after simulation and evaluation succeed; failures are counted on the run, never fabricated.

## Results

**No real-model benchmark has been run yet** (no API key was available while building). `reports/benchmark_report.md` currently holds a complete **MOCK** run (75 conversations, 0 failures) that proves the pipeline end to end. Mock "differences" between strategies are artifacts of a deterministic rule-based stack (it only varies phrasing/timing via a hash of the prompt) and must not be read as findings.

After a real run, the report is regenerated from the database with tables for every metric, per-category and per-scenario analysis, paired win/tie/loss counts, failure cases, standard errors and limitations.

### Running the real benchmark

```bash
# 1. get a free key at https://console.groq.com/keys and put it in .env (never in chat or git)
#    GROQ_API_KEY=gsk_...

cd backend
# 2. verify the model names against the live API and see your real rate limits
python -m app.cli verify-models

# 3. run (verifies again automatically, prints a size estimate, then runs)
python -m app.cli benchmark
python -m app.cli report
```

Defaults (all live-verified): agent `qwen/qwen3.8-27b` (thinking off), customer simulator `openai/gpt-oss-20b`, judge `openai/gpt-oss-120b` (a different family from the agent, to reduce self-preference bias). Change them with `LLM_MODEL`, `SIMULATOR_MODEL`, `JUDGE_MODEL`; the models used are stored on the run and `--resume` refuses to mix models.

**Free-tier reality check.** A full 25 x 3 run is roughly 1.26M tokens and about 750 requests (the CLI prints the estimate). Verified free limits are 1,000 requests/day and 8,000 tokens/min per model, so expect about 2.5 hours of pacing, and daily token quotas may be smaller than the run. When Groq answers with a long `retry-after` the run stops cleanly as `partial` and you continue later:

```bash
python -m app.cli benchmark --resume <run-id>
```

To start smaller: `--variants persona zero_shot`, `--scenarios disc-excel price-expensive ...`, or `--max-turns 5`. Rate-limit waits are never counted as model latency; only the successful request is timed. Browser TTS is not timed in benchmarks.

## SQL analytics

`sql/analysis.sql` has 17 PostgreSQL queries: mean overall score, goal completion rate, objection handling, quality, average / P50 / P95 latency, performance by scenario / difficulty / category, prompt x scenario matrix, failure cases, high-latency conversations, completed demos, score distributions, stop reasons and live voice latency. They read the views `conversation_results`, `turn_latencies` and `latest_benchmark_run`, and `tests/test_sql_analysis.py` executes every one against real benchmark data.

```bash
psql "postgresql://salesagent:salesagent@localhost:5433/salesagent" -f sql/analysis.sql
# no local psql? use the container:
docker exec -i hinglish-sales-agent-db psql -U salesagent -d salesagent -f - < sql/analysis.sql
```

## Local setup

Prerequisites: Python 3.11+, Node 20+, Docker (or any PostgreSQL 14+).

```bash
# 1. Database (host port 5433 so it does not clash with a local PostgreSQL on 5432)
docker compose up -d

# 2. Configuration
cp .env.example .env            # Windows: copy .env.example .env

# 3. Backend
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
python -m app.cli seed
uvicorn app.main:app --reload   # http://localhost:8000/docs

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

No keys at all? Leave them empty: the app runs on mock providers and says so in the UI. With only `GROQ_API_KEY` the whole stack is real and free. Without Docker, point `DATABASE_URL` at any PostgreSQL and create the database first.

To use the microphone the page must be on `localhost` or HTTPS. Spoken replies use your browser's installed voices (an Indian-English voice if available), so voice quality depends on the OS/browser.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `GROQ_API_KEY` | empty | Free key. Enables the real LLM (agent, simulator, judge) and Groq Whisper STT. Never logged or returned by the API. |
| `OPENAI_API_KEY` | empty | Optional and paid: only for OpenAI STT/TTS |
| `DATABASE_URL` | compose DB on 5433 | SQLAlchemy URL with the `postgresql+psycopg://` driver |
| `LLM_MODEL` | `qwen/qwen3.8-27b` | Sales agent (thinking disabled) |
| `SIMULATOR_MODEL` | `openai/gpt-oss-20b` | Customer simulator (own quota pool) |
| `JUDGE_MODEL` | `openai/gpt-oss-120b` | Evaluator; reasoning model, so it gets a larger output budget |
| `STT_MODEL` | empty | Empty = `whisper-large-v3-turbo` (Groq) or `gpt-4o-mini-transcribe` (OpenAI) |
| `TTS_MODEL`, `TTS_VOICE` | `gpt-4o-mini-tts`, `ash` | OpenAI TTS only |
| `PROVIDER_MODE` | `auto` | `auto` (use what has credentials), `mock` (force mocks), `live` (require `GROQ_API_KEY`) |
| `STT_PROVIDER` / `TTS_PROVIDER` | `auto` | STT: `auto\|groq\|openai\|mock`. TTS: `auto\|openai\|browser\|mock` (auto = OpenAI if keyed, else free browser voice) |
| `APP_ENV`, `LOG_LEVEL`, `CORS_ORIGINS` | development, INFO, `http://localhost:3000` | |
| `LLM_MAX_RETRIES`, `MAX_RETRY_WAIT_S`, `JUDGE_MAX_OUTPUT_TOKENS`, `REASONING_EFFORT` | 4, 90, 2000, `low` | Rate-limit handling and reasoning-model budget |
| `MAX_AUDIO_BYTES`, `BENCHMARK_MAX_TURNS`, `BENCHMARK_INCLUDE_TTS`, `BENCHMARK_CONCURRENCY` | 10 MB, 8, true, 1 | |

Frontend: `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

## Testing

```bash
cd backend
pytest                          # needs PostgreSQL; uses a separate <db>_test database
python -m mypy app --ignore-missing-imports
```

The suite builds its schema by running the Alembic migrations (so migrations are tested), and covers: prompt registry, 25 scenarios, conversation state and history, simulator isolation, evaluator parsing / scoring / blindness, DB inserts and constraints, API endpoints and failure paths (STT failure, LLM timeout, TTS fallback, bad audio, path traversal), the benchmark runner (paired scenarios, max turns, resume, failure accounting), every SQL query, the Groq LLM provider (payloads, reasoning parameters, retries, quota exhaustion, error mapping), the model-verification preflight, and the STT/TTS provider wiring, all against a fake HTTP transport. Frontend: `npm run lint && npm run build`.

## Project structure

```
backend/
  app/
    api/            FastAPI routers (system, voice, conversations, evaluations, benchmark)
    agent/          conversation state, sales agent, customer simulator
    prompts/        prompt registry (zero-shot, few-shot, persona)
    providers/      STT/LLM/TTS interfaces; Groq LLM, OpenAI-style STT/TTS, browser TTS, mocks; model_check.py
    evaluation/     LLM-as-judge evaluator and scoring
    benchmark/      runner and report generator
    voice/          audio validation and the voice pipeline
    db/             models, session, repository
    scenarios/      scenarios.json + loader/seeder
    storage/        audio storage abstraction (local disk; S3/R2-ready)
    product.py      single source of truth for FlowDesk facts
    analytics.py    dashboard / explorer queries
    cli.py          seed | benchmark | report
  alembic/          migrations (schema + analytics views)
  tests/
frontend/           Next.js app (Voice, Evaluation, Conversations)
sql/analysis.sql    analytics queries
reports/            generated benchmark report
docs/               project summary, resume material, model verification record
docker-compose.yml  PostgreSQL
```

## Future improvements

- Run and publish the real benchmark with multiple simulator seeds; add a small human-labelled calibration set and check Groq Whisper's Hinglish accuracy.
- Streaming STT/LLM/TTS and barge-in to cut perceived voice latency.
- Prompt versioning with automatic regression runs in CI.
- Cloud audio storage (S3/R2) behind the existing `AudioStorage` interface.
- Per-scenario confidence intervals and significance tests.
