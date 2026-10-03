# Model verification

Model names are configuration (`.env`), never hard-coded. Two layers of verification exist.

## 1. Live verification (code, run before every real benchmark)

```bash
cd backend
python -m app.cli verify-models        # list + smoke-test every configured model
python -m app.cli verify-models --no-smoke   # list only (no tokens spent)
```

For each configured model it:

1. calls the provider's `GET /models` and confirms the name exists right now;
2. smoke-tests each LLM through the same provider code path the benchmark uses, with the same parameters (JSON mode, `reasoning_effort` for `openai/gpt-oss-*`), so unsupported parameters fail here and not 40 minutes into a run;
3. reads the account's `x-ratelimit-*` response headers and prints the real per-minute / per-day limits;
4. checks the OpenAI STT/TTS model names and TTS voice only if those paid providers are selected.

`python -m app.cli benchmark` and `POST /api/benchmark/run` run this check automatically for real providers and refuse to start if any model is missing or a smoke call fails (override: `--skip-model-check`). Every run records the models it used in `benchmark_runs.config.models`, and `--resume` refuses to continue a run with different models.

Exit codes: `0` verified, `1` verification failed, `2` could not verify (no `GROQ_API_KEY`, so everything is a mock).

## Live verification result (2026-10-03)

Run with a real free-tier Groq key:

```
agent      groq  qwen/qwen3.8-27b          ok  listed; smoke call ok (182 ms)
simulator  groq  openai/gpt-oss-20b        ok  listed; smoke call ok (459 ms)
judge      groq  openai/gpt-oss-120b       ok  listed; smoke call ok (517 ms)
stt        groq  whisper-large-v3-turbo    ok  listed by the API
tts        browser  (client-side)          skipped
rate limits (each of the three LLMs): 1000 requests/day, 8000 tokens/min
```

**The first run failed, and that is the point of the check.** The Groq docs pages listed `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` as production models, but the live `GET /models` for this account did not contain them (live chat-capable models: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`, `allam-2-7b`; plus Whisper, Orpheus TTS and prompt-guard models). Documentation and the live API disagreed, so the defaults were changed to models the API actually serves. Treat the table below as documentation claims, and the result above as the ground truth. The model list can differ per account and over time, so re-run `verify-models` before each real benchmark.

The smoke calls also confirmed the request parameters the code sends are accepted: JSON mode on all three LLMs, `reasoning_effort: "none"` + `reasoning_format: "hidden"` on Qwen, and `reasoning_effort` + `include_reasoning: false` on gpt-oss.

## 2. Documentation check (done 2026-10-03)

Checked against the providers' published documentation before a key was available. Page content was read through a summarising fetch tool, and **it turned out to be wrong for the two Llama models** (see above), so this table is a hint only.

| Role | Configured model | Provider | What the docs say / live outcome |
|---|---|---|---|
| Sales agent | `qwen/qwen3.8-27b` | Groq | Docs: preview model, 131k context, `reasoning_effort` accepts `none`/`default`/`low`/`medium`/`high`. Live: listed, smoke call ok. Run with thinking off for latency |
| Customer simulator | `openai/gpt-oss-20b` | Groq | Docs: production, `reasoning_effort` low/medium/high, reasoning tokens count toward the output limit. Live: listed, smoke call ok. Own quota pool |
| Judge | `openai/gpt-oss-120b` | Groq | Docs: production, `json_object` and strict `json_schema`. Live: listed, smoke call ok. Different family from the agent |
| ~~Agent / simulator~~ | ~~`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`~~ | Groq | Docs: production, no deprecation. **Live: not in this account's model list, removed from defaults** |
| Speech-to-text | `whisper-large-v3-turbo` | Groq | Docs: production; `/openai/v1/audio/transcriptions`; `prompt` up to 224 tokens; formats flac/mp3/mp4/mpeg/mpga/m4a/ogg/wav/webm. Live: listed. Hindi is not explicitly documented, so check Hinglish accuracy by ear |
| Speech-to-text (optional) | `gpt-4o-mini-transcribe` | OpenAI | Docs: listed; supports `prompt`; OpenAI now also recommends `gpt-transcribe`. Not checked live (no OpenAI key) |
| Text-to-speech (optional) | `gpt-4o-mini-tts`, voice `ash` | OpenAI | Docs: listed; `ash` valid; only this model documents `instructions`. Not checked live |
| Text-to-speech (free) | browser `speechSynthesis` | none | Not a model. Groq's TTS is English/Arabic only (Orpheus), not Hindi |

API facts the code depends on, from the Groq docs: base URL `https://api.groq.com/openai/v1`; `seed`, `response_format: json_object` and `max_completion_tokens` are supported; JSON mode requires the word "JSON" in the prompt (the simulator and judge prompts include it); `include_reasoning` and `reasoning_format` are mutually exclusive; `reasoning_format` is not supported on gpt-oss models; a `retry-after` header is sent with 429 responses.

Free-tier limits: the Groq rate-limit page quotes `openai/gpt-oss-120b` at 30 requests/min, 1K requests/day, 8K tokens/min, 200K tokens/day, and Whisper at 20 requests/min, 2K requests/day. Live headers from this account confirmed 1,000 requests/day and 8,000 tokens/min for each of the three LLMs; the per-day *token* limit is not exposed in headers, so check https://console.groq.com/settings/limits. Whether a credit card is required for the free plan was not stated in the docs I could read.

## Sources

- https://console.groq.com/docs/models
- https://console.groq.com/docs/deprecations
- https://console.groq.com/docs/openai
- https://console.groq.com/docs/api-reference
- https://console.groq.com/docs/structured-outputs
- https://console.groq.com/docs/reasoning
- https://console.groq.com/docs/speech-to-text
- https://console.groq.com/docs/text-to-speech
- https://console.groq.com/docs/rate-limits
- https://developers.openai.com/api/docs/guides/speech-to-text
- https://developers.openai.com/api/docs/guides/text-to-speech

## Free-tier budget

`python -m app.cli benchmark` prints a rough estimate before starting. For the full 25 x 3 run with the current defaults: `qwen/qwen3.8-27b` about 375 requests / 620K tokens, `openai/gpt-oss-20b` about 300 requests / 440K tokens, `openai/gpt-oss-120b` about 75 requests / 200K tokens (including reasoning). Request counts fit the 1,000/day limit. The 8,000 tokens/min limit means roughly 2.5 hours of pacing in total, and daily *token* quotas (not visible in headers) may be lower than the estimate. The runner handles this: a 429 with a short `retry-after` is waited out (not counted as latency); a long one (> 90 s) is treated as an exhausted quota, the run stops cleanly as `partial`, and `--resume <run-id>` continues the missing cells after the quota resets. Each model has its own quota pool, which is why the simulator and judge use different models than the agent.
