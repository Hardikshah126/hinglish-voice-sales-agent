"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ApiError,
  apiGet,
  type ConversationDetail,
  type ConversationItem,
  type ConversationList,
  type Latency,
  type Scenario,
} from "@/lib/api";
import { ms, num, titleCase, VARIANT_LABEL } from "@/lib/format";
import { Card, ErrorNote, Pill, Skeleton, VariantChip } from "@/components/ui";

const PAGE_SIZE = 25;
const CATEGORIES = [
  "discovery",
  "price_objection",
  "existing_solution",
  "trust",
  "timing",
  "buying_intent",
  "difficult_customer",
];

interface Filters {
  prompt_variant: string;
  scenario_id: string;
  category: string;
  goal: string; // "" | "yes" | "no"
  min_score: string;
  run_mode: string;
  source: string;
}
const EMPTY: Filters = { prompt_variant: "", scenario_id: "", category: "", goal: "", min_score: "", run_mode: "", source: "" };

function Select({ label, value, onChange, children }: { label: string; value: string; onChange: (v: string) => void; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-border bg-surface-2 px-2.5 py-1.5 text-sm text-foreground"
      >
        {children}
      </select>
    </label>
  );
}

export default function ConversationsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <ConversationsView />
    </Suspense>
  );
}

interface Page {
  key: string;
  items: ConversationItem[];
  total: number;
}

function ConversationsView() {
  const router = useRouter();
  const selectedId = useSearchParams().get("id"); // the URL is the source of truth for the selection
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Scenario[]>("/api/scenarios").then(setScenarios).catch(() => undefined);
  }, []);

  const params = useMemo(
    () => ({
      prompt_variant: filters.prompt_variant,
      scenario_id: filters.scenario_id,
      category: filters.category,
      goal_completed: filters.goal === "yes" ? "true" : filters.goal === "no" ? "false" : "",
      min_score: filters.min_score,
      run_mode: filters.run_mode,
      source: filters.source,
    }),
    [filters],
  );

  const fetchPage = useCallback(
    async (offset: number) => {
      const data = await apiGet<ConversationList>("/api/conversations", { ...params, limit: PAGE_SIZE, offset });
      return data;
    },
    [params],
  );

  const key = JSON.stringify(params);
  useEffect(() => {
    let cancelled = false;
    fetchPage(0)
      .then((d) => {
        if (cancelled) return;
        setPage({ key, items: d.items, total: d.total });
        setError(null);
      })
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Failed to load conversations."));
    return () => {
      cancelled = true;
    };
  }, [fetchPage, key]);

  // A result only counts as loaded if it belongs to the current filters.
  const loading = page?.key !== key;
  const items = page && page.key === key ? page.items : [];
  const total = page && page.key === key ? page.total : 0;

  const loadMore = async () => {
    try {
      const d = await fetchPage(items.length);
      setPage((p) => (p && p.key === key ? { ...p, items: [...p.items, ...d.items], total: d.total } : p));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load more.");
    }
  };

  const select = (id: string | null) =>
    router.replace(id ? `/conversations?id=${id}` : "/conversations", { scroll: false });

  const set = (key: keyof Filters) => (value: string) => setFilters((f) => ({ ...f, [key]: value }));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Conversation Explorer</h1>
        <p className="mt-1 text-sm text-muted">Every stored conversation with its transcript, evaluation and latency.</p>
      </div>

      <Card>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          <Select label="Prompt strategy" value={filters.prompt_variant} onChange={set("prompt_variant")}>
            <option value="">All</option>
            {Object.entries(VARIANT_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </Select>
          <Select label="Scenario" value={filters.scenario_id} onChange={set("scenario_id")}>
            <option value="">All</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
          <Select label="Category" value={filters.category} onChange={set("category")}>
            <option value="">All</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {titleCase(c)}
              </option>
            ))}
          </Select>
          <Select label="Goal completion" value={filters.goal} onChange={set("goal")}>
            <option value="">Any</option>
            <option value="yes">Achieved</option>
            <option value="no">Not achieved</option>
          </Select>
          <Select label="Min overall score" value={filters.min_score} onChange={set("min_score")}>
            <option value="">Any</option>
            {[1, 2, 3, 4, 4.5].map((n) => (
              <option key={n} value={n}>
                ≥ {n}
              </option>
            ))}
          </Select>
          <Select label="Providers" value={filters.run_mode} onChange={set("run_mode")}>
            <option value="">All</option>
            <option value="real">Real</option>
            <option value="mock">Mock</option>
          </Select>
          <Select label="Source" value={filters.source} onChange={set("source")}>
            <option value="">All</option>
            <option value="benchmark">Benchmark</option>
            <option value="voice">Live voice</option>
          </Select>
        </div>
        {JSON.stringify(filters) !== JSON.stringify(EMPTY) && (
          <button type="button" onClick={() => setFilters(EMPTY)} className="mt-3 text-xs text-accent hover:underline">
            Clear filters
          </button>
        )}
      </Card>

      {error && <ErrorNote message={error} />}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,380px)_1fr]">
        <div className={selectedId ? "hidden lg:block" : ""}>
          <div className="mb-2 text-xs text-muted tabular">
            {loading ? "Loading…" : `${total} conversation${total === 1 ? "" : "s"}`}
          </div>
          {loading && items.length === 0 ? (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <Card>
              <p className="py-6 text-center text-sm text-muted">
                No conversations match. Run the benchmark on the Evaluation page or talk to the agent on the Voice page.
              </p>
            </Card>
          ) : (
            <ul className="space-y-2" aria-label="Conversations">
              {items.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => select(c.id)}
                    aria-current={selectedId === c.id}
                    className={`w-full rounded-xl border p-3 text-left transition-colors hover:border-accent ${
                      selectedId === c.id ? "border-accent bg-surface-2" : "border-border bg-surface"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-sm font-medium">{c.scenario_name ?? "Live voice conversation"}</span>
                      {c.overall_score !== null && (
                        <span className="tabular shrink-0 text-sm font-semibold">{c.overall_score.toFixed(2)}</span>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <VariantChip variant={c.prompt_variant} />
                      {c.run_mode === "mock" && <Pill tone="warn">mock</Pill>}
                      {c.goal_completed === true && <Pill tone="ok">goal achieved</Pill>}
                      {c.goal_completed === false && <Pill tone="danger">goal missed</Pill>}
                      {c.category && <span className="text-xs text-muted">{titleCase(c.category)}</span>}
                      <span className="text-xs text-muted">· {c.turn_count} turns</span>
                    </div>
                  </button>
                </li>
              ))}
              {items.length < total && (
                <li>
                  <button
                    type="button"
                    onClick={loadMore}
                    className="w-full rounded-lg border border-border py-2 text-sm text-muted hover:bg-surface-2"
                  >
                    Load more ({total - items.length} remaining)
                  </button>
                </li>
              )}
            </ul>
          )}
        </div>

        <div className={selectedId ? "" : "hidden lg:block"}>
          {selectedId ? (
            <Detail key={selectedId} id={selectedId} onBack={() => select(null)} />
          ) : (
            <Card>
              <p className="py-16 text-center text-sm text-muted">Select a conversation to see its transcript and evaluation.</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function Score({ label, value, max }: { label: string; value: number | null; max: number }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className="tabular text-lg font-semibold">
        {value === null ? <span className="text-sm font-normal text-muted">N/A</span> : `${value}/${max}`}
      </div>
    </div>
  );
}

function Detail({ id, onBack }: { id: string; onBack: () => void }) {
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<ConversationDetail>(`/api/conversations/${id}`)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Failed to load conversation."));
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) return <ErrorNote message={error} />;
  if (!detail) return <Skeleton className="h-96" />;

  const ev = detail.evaluation;
  const lat: Latency | null = detail.latency_summary;
  const sc = detail.scenario;

  return (
    <div className="space-y-4">
      <Card>
        <button type="button" onClick={onBack} className="mb-2 text-xs text-accent hover:underline lg:hidden">
          ← Back to list
        </button>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-xs uppercase tracking-wide text-muted">Scenario</div>
            <h2 className="text-lg font-semibold tracking-tight">{sc?.name ?? "Live voice conversation"}</h2>
            {sc && (
              <div className="mt-0.5 text-sm text-muted">
                {titleCase(sc.category)} · difficulty {sc.difficulty}/5
              </div>
            )}
          </div>
          <div className="text-right">
            <div className="text-xs uppercase tracking-wide text-muted">Prompt strategy</div>
            <div className="mt-1 flex flex-wrap items-center justify-end gap-1.5">
              <VariantChip variant={detail.prompt_variant} />
              {detail.run_mode === "mock" && <Pill tone="warn">mock providers</Pill>}
            </div>
            <div className="mt-1 font-mono text-[11px] text-muted">
              prompt {detail.prompt_hash} · {detail.llm_model ?? "n/a"}
            </div>
          </div>
        </div>
        {sc && (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-muted hover:text-foreground">Scenario details</summary>
            <dl className="mt-2 space-y-2">
              <div>
                <dt className="text-xs text-muted">Customer profile</dt>
                <dd>{sc.customer_profile}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">Goal</dt>
                <dd>{sc.goal}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">Completion criteria</dt>
                <dd>
                  <ul className="list-disc pl-5">
                    {sc.completion_criteria.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </dd>
              </div>
              {sc.expected_objection && (
                <div>
                  <dt className="text-xs text-muted">Expected objection</dt>
                  <dd>{sc.expected_objection}</dd>
                </div>
              )}
            </dl>
          </details>
        )}
      </Card>

      <Card title="Transcript" action={detail.stop_reason && <span className="text-xs text-muted">ended: {titleCase(detail.stop_reason)}</span>}>
        <ol className="space-y-3">
          {detail.turns.map((t) => (
            <li key={t.id} className={`flex ${t.speaker === "customer" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[88%] rounded-2xl px-3.5 py-2 text-sm ${
                  t.speaker === "customer" ? "rounded-br-sm bg-accent text-accent-fg" : "rounded-bl-sm border border-border bg-surface-2"
                }`}
              >
                <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide opacity-70">
                  {t.speaker === "customer" ? "Customer" : "Agent"} · turn {t.turn_number}
                </div>
                {t.text}
                {t.latency && (
                  <div className="tabular mt-1 text-[11px] text-muted">
                    {t.latency.stt_ms !== null && <>STT {ms(t.latency.stt_ms)} · </>}
                    LLM {ms(t.latency.llm_ms)}
                    {t.latency.tts_ms !== null && <> · TTS {ms(t.latency.tts_ms)}</>} · total {ms(t.latency.total_ms)}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Evaluation">
          {ev ? (
            <>
              <div className="grid grid-cols-3 gap-2">
                <Score label="Goal completion" value={ev.goal_completion_score} max={2} />
                <Score label="Objection handling" value={ev.objection_handling_score} max={3} />
                <Score label="Quality" value={ev.conversation_quality_score} max={5} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
                <span className="tabular font-semibold">Overall {num(ev.overall_score)} / 5</span>
                {ev.invented_claims && <Pill tone="danger">invented claims flagged</Pill>}
              </div>
              <p className="mt-2 text-sm text-muted">{ev.reasoning}</p>
              <p className="mt-2 text-xs text-muted">Judge: {ev.judge_model}</p>
            </>
          ) : (
            <p className="text-sm text-muted">This conversation has not been evaluated (live voice conversations are not scored).</p>
          )}
        </Card>

        <Card title="Latency (mean per agent turn)">
          {lat ? (
            <>
              <dl className="tabular grid grid-cols-[1fr_auto] gap-y-1.5 text-sm">
                <dt className="text-muted">STT</dt>
                <dd>{lat.stt_ms === null ? "not measured" : ms(lat.stt_ms)}</dd>
                <dt className="text-muted">LLM</dt>
                <dd>{ms(lat.llm_ms)}</dd>
                <dt className="text-muted">TTS</dt>
                <dd>{lat.tts_ms === null ? "not measured" : ms(lat.tts_ms)}</dd>
                <dt className="border-t border-border pt-1.5 font-semibold">Total</dt>
                <dd className="border-t border-border pt-1.5 font-semibold">{ms(lat.total_ms)}</dd>
              </dl>
              <p className="mt-3 text-xs text-muted">
                {detail.source === "benchmark"
                  ? "Simulated-benchmark latency: text input, so no STT stage."
                  : "Real voice pipeline latency from a live request."}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">No latency recorded.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
