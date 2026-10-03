# Benchmark Report

> **MOCK RESULTS.** These results were generated using mock providers and are not representative of production model performance. They only demonstrate that the benchmark pipeline (simulation, evaluation, storage, analytics) works end to end.

- Run id: `27a23e43-72a2-4ae0-a3a9-6a587aa67fd5`
- Provider mode: **MOCK**
- Models: agent `mock-llm`, judge `mock-judge`, simulator `mock-llm`
- Status: completed — 75 of 75 conversations completed, 0 failed
- Generated: 2026-10-03 23:33 India Standard Time

## Dataset

25 scenarios across 7 categories (discovery, price objections, existing solutions, trust, timing, buying intent, difficult customers), difficulty 1-5. 75 evaluated conversations in this run.

## Prompt Strategies

- **Zero-shot**: Product facts, objective, language requirement and basic constraints only.
- **Few-shot**: Base brief plus five worked Hinglish example dialogues.
- **Persona**: Base brief plus a detailed consultative sales persona (Kavya).

All three share an identical base brief (product facts, objective, language requirement, constraints); only the strategy-specific layer differs.

## Methodology

- Every scenario is run once per strategy against the **same customer simulator** (same model, temperature and seed). The simulator never sees the strategy.
- Up to 8 turns (customer message + agent reply); the conversation stops early once the simulated customer clearly agrees to the scenario goal or walks away.
- Each conversation is scored by one LLM judge with a fixed rubric (goal completion 0-2, objection handling 0-3 or N/A, conversation quality 1-5, invented-claims flag). The judge sees the scenario and transcript only, never the strategy.
- Overall score (0-5) = weighted mean of normalised dimensions (goal 0.4, objection 0.3, quality 0.3; objection weight dropped when N/A).
- Latency is measured with a monotonic clock around each provider call. Benchmark latency is measured per agent turn with a monotonic clock, but customer input is text (no speech-to-text) and conversations run server-side. It is simulated-benchmark latency, not real end-to-end voice latency.

## Goal Completion

| Metric | Zero-shot | Few-shot | Persona |
|---|---|---|---|
| Goal completion rate | 96.0% (24/25) | 96.0% (24/25) | 84.0% (21/25) |
| Mean goal score (0-2) | 1.96 | 1.96 | 1.84 |

## Objection Handling

| Metric | Zero-shot | Few-shot | Persona |
|---|---|---|---|
| Mean score (0-3) | 2.70 | 2.90 | 2.70 |
| Conversations with an objection | 20 | 20 | 20 |

## Conversation Quality

| Metric | Zero-shot | Few-shot | Persona |
|---|---|---|---|
| Mean quality (1-5) | 3.60 | 3.76 | 3.56 |
| Mean overall (0-5) | 4.39 | 4.52 | 4.25 |
| Conversations with invented claims | 0 | 0 | 0 |

## Latency

| Metric | Zero-shot | Few-shot | Persona |
|---|---|---|---|
| Avg total (ms) | 6.9 | 6.1 | 6.2 |
| P50 total (ms) | 7.0 | 5.3 | 5.5 |
| P95 total (ms) | 13.5 | 11.4 | 11.2 |
| Avg LLM (ms) | 0.1 | 0.1 | 0.1 |
| Avg TTS (ms) | 6.8 | 6.1 | 6.1 |
| Agent turns measured | 117 | 139 | 134 |

STT latency is not part of benchmark runs (customer input is text). Real end-to-end voice latency is recorded separately for live conversations (`source = 'voice'`, see query 17 in `sql/analysis.sql`).

## Scenario Analysis

| Category | Zero-shot | Few-shot | Persona |
|---|---|---|---|
| Buying Intent | 4.48 | 4.60 | 4.48 |
| Difficult Customer | 4.08 | 4.08 | 3.72 |
| Discovery | 4.53 | 4.70 | 4.53 |
| Existing Solution | 4.22 | 4.55 | 3.98 |
| Price Objection | 4.58 | 4.50 | 4.25 |
| Timing | 4.60 | 4.60 | 4.50 |
| Trust | 4.30 | 4.70 | 4.50 |

Mean overall score (0-5) per scenario:

| Scenario | Category | Diff. | Zero-shot | Few-shot | Persona |
|---|---|---|---|---|---|
| Wants a demo | buying intent | 1 | 4.57 | 4.57 | 4.57 |
| Asks how to get started | buying intent | 1 | 4.57 | 4.57 | 4.57 |
| Asks implementation details | buying intent | 2 | 4.57 | 4.57 | 4.57 |
| Asks about pricing | buying intent | 2 | 4.20 | 4.70 | 4.20 |
| Impatient customer | difficult customer | 4 | 4.20 | 4.20 | 2.90 |
| Asks unrelated questions | difficult customer | 4 | 4.57 | 4.57 | 4.14 |
| One-word answers | difficult customer | 5 | 4.14 | 4.14 | 4.14 |
| Skeptical customer | difficult customer | 5 | 3.40 | 3.40 | 3.70 |
| Currently uses Excel | discovery | 1 | 4.70 | 4.70 | 4.70 |
| Growing team losing track of leads | discovery | 2 | 4.20 | 4.70 | 4.20 |
| No CRM at all | discovery | 2 | 4.70 | 4.70 | 4.70 |
| Already uses HubSpot | existing solution | 3 | 4.20 | 4.70 | 4.20 |
| Already uses Zoho | existing solution | 3 | 4.40 | 4.40 | 4.40 |
| Built an internal tool | existing solution | 4 | 4.40 | 4.70 | 3.40 |
| Already uses Salesforce | existing solution | 4 | 3.90 | 4.40 | 3.90 |
| Wants a free version | price objection | 2 | 4.20 | 3.90 | 4.20 |
| Competitor is cheaper | price objection | 3 | 4.70 | 4.70 | 4.70 |
| Too expensive | price objection | 3 | 4.70 | 4.70 | 4.70 |
| No budget | price objection | 4 | 4.70 | 4.70 | 3.40 |
| Too busy, call next month | timing | 3 | 4.40 | 4.70 | 4.40 |
| Needs manager approval | timing | 3 | 4.70 | 4.70 | 4.40 |
| Needs to think about it | timing | 3 | 4.70 | 4.40 | 4.70 |
| Concerned about data security | trust | 3 | 4.10 | 4.70 | 4.40 |
| Worried about migration and implementation | trust | 3 | 4.40 | 4.70 | 4.40 |
| Never heard of FlowDesk | trust | 3 | 4.40 | 4.70 | 4.70 |

Paired comparison of overall score across scenarios (wins / ties / losses for the first strategy):

| Comparison | Wins | Ties | Losses |
|---|---|---|---|
| Zero-shot vs Few-shot | 2 | 14 | 9 |
| Zero-shot vs Persona | 5 | 17 | 3 |
| Few-shot vs Persona | 12 | 10 | 3 |

## Failure Cases

No conversation had goal score 0 or overall score below 2.5.

## Interesting Observations

Mock providers use rule-based logic, so no conclusion about prompt strategies can be drawn from these numbers. Run the benchmark with a real API key to produce observations.

## Limitations

- One run per scenario/strategy cell with a stochastic simulator: no confidence intervals beyond the standard errors below, and differences of a few tenths of a point on 25 scenarios should not be treated as significant.
- The judge is an LLM and may share biases with the agent model; no human calibration set has been collected yet.
- The simulator is a model playing a customer, not real customers.
- Benchmark latency excludes STT and network conditions of real users.
- Scenarios are written for one fictional product (FlowDesk).

Standard error of mean overall score: Zero-shot ±0.06, Few-shot ±0.06, Persona ±0.09

## Next Experiments

- Repeat each cell with several simulator seeds and report variance.
- Use a different model family as judge and measure judge agreement.
- Add a human-labelled calibration set of 20-30 conversations.
- Combine few-shot and persona, and ablate the number of examples.
- Measure real voice latency across devices and networks.

---

> **MOCK RESULTS.** These results were generated using mock providers and are not representative of production model performance. They only demonstrate that the benchmark pipeline (simulation, evaluation, storage, analytics) works end to end.
