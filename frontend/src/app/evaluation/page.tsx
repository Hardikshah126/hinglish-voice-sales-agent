"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ApiError,
  apiGet,
  apiPost,
  type BenchmarkStatus,
  type EvaluationSummary,
  type Flag,
  type ScenarioRow,
  type ScoreDistribution,
  type Variant,
  type VariantSummary,
} from "@/lib/api";
import { heat, ms, num, pct, titleCase, VARIANT_COLOR, VARIANT_LABEL } from "@/lib/format";
import { Card, ErrorNote, MockBanner, Pill, Skeleton, Stat, VariantChip } from "@/components/ui";

type Mode = "auto" | "mock" | "real";

const TOOLTIP_STYLE = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  color: "var(--foreground)",
  fontSize: 12,
};
const AXIS = { fontSize: 12, fill: "var(--muted)" };

export default function EvaluationPage() {
  const [mode, setMode] = useState<Mode>("auto");
  const [summary, setSummary] = useState<EvaluationSummary | null>(null);
  const [status, setStatus] = useState<BenchmarkStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [distMetric, setDistMetric] = useState<ScoreDistribution["metric"]>("quality");

  // Results are applied in promise callbacks, never synchronously inside an effect body.
  const refresh = useCallback(
    () =>
      Promise.all([
        apiGet<EvaluationSummary>("/api/evaluations/summary", mode === "auto" ? {} : { run_mode: mode }),
        apiGet<BenchmarkStatus>("/api/benchmark"),
      ])
        .then(([s, b]) => {
          setSummary(s);
          setStatus(b);
          setError(null);
        })
        .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load results.")),
    [mode],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!status?.is_running) return;
    const id = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(id);
  }, [status?.is_running, refresh]);

  const runBenchmark = async () => {
    setStarting(true);
    try {
      await apiPost("/api/benchmark/run", {});
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the benchmark.");
    } finally {
      setStarting(false);
    }
  };

  if (!summary && !error) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64" />
        <Skeleton className="h-80" />
      </div>
    );
  }

  const run = summary?.benchmark_run ?? null;
  const running = status?.is_running ?? false;
  const latest = status?.latest_run;
  const providerLabel = status?.llm_provider === "groq" ? "Groq" : "mock";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Prompt Evaluation</h1>
          <p className="mt-1 text-sm text-muted">
            Zero-shot vs few-shot vs persona prompting, on identical simulated customers and one fixed judge rubric.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {summary && summary.available_modes.length > 1 && (
            <div role="group" aria-label="Result set" className="flex overflow-hidden rounded-lg border border-border text-sm">
              {(["auto", "real", "mock"] as Mode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                  className={`px-3 py-1.5 ${mode === m ? "bg-surface-2 font-medium" : "text-muted hover:bg-surface-2"}`}
                >
                  {m === "auto" ? "Latest" : m === "real" ? "Real" : "Mock"}
                </button>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={runBenchmark}
            disabled={running || starting}
            className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            {running ? "Running…" : `Run benchmark (${providerLabel})`}
          </button>
        </div>
      </div>

      {error && <ErrorNote message={error} />}
      {summary?.is_mock && <MockBanner />}
      {status?.llm_provider === "groq" && !running && (
        <p className="text-xs text-muted">
          Models: {Object.entries(status.models).map(([role, model]) => `${role} ${model}`).join(" · ")}. A full run is ~1.3M tokens;
          on Groq&apos;s free tier it may stop at a daily quota and can be resumed from the CLI (--resume).
        </p>
      )}

      {running && latest && (
        <Card>
          <div className="flex items-center justify-between text-sm">
            <span>
              Benchmark running ({latest.run_mode}): {latest.completed_conversations + latest.failed_conversations} /{" "}
              {latest.total_conversations} conversations
            </span>
            <span className="tabular text-muted">{latest.failed_conversations} failed</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full bg-accent transition-all"
              style={{
                width: `${(100 * (latest.completed_conversations + latest.failed_conversations)) / Math.max(1, latest.total_conversations)}%`,
              }}
            />
          </div>
        </Card>
      )}

      {summary && !run && (
        <Card>
          <div className="py-10 text-center">
            <div className="text-lg font-medium">Benchmark not yet run</div>
            <p className="mx-auto mt-1 max-w-md text-sm text-muted">
              Runs {status?.scenario_count ?? 25} scenarios × 3 prompt strategies = {(status?.scenario_count ?? 25) * 3}{" "}
              controlled conversations, evaluates each one, and stores everything in PostgreSQL.
            </p>
          </div>
        </Card>
      )}

      {summary && run && (
        <>
          <MetricsTable summary={summary} />
          <div className="grid gap-4 lg:grid-cols-2">
            <ScoreChart variants={summary.by_variant} />
            <LatencyCard summary={summary} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <DistributionCard distributions={summary.distributions} metric={distMetric} onMetric={setDistMetric} />
            <CategoryCard summary={summary} />
          </div>
          <Heatmap summary={summary} />
          <div className="grid gap-4 lg:grid-cols-2">
            <FlagList title="Failure cases" empty="No conversation scored 0 on goal or below 2.5 overall." items={summary.failure_cases} />
            <FlagList title="Highest latency conversations" empty="No latency data." items={summary.high_latency} showLatency />
          </div>
          <p className="text-xs text-muted">{summary.latency_note}</p>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
function MetricsTable({ summary }: { summary: EvaluationSummary }) {
  const v = summary.by_variant;
  const rows: {
    label: string;
    get: (x: VariantSummary) => number | null;
    show: (x: VariantSummary) => string;
    lowerIsBetter?: boolean;
  }[] = [
    { label: "Goal Completion", get: (x) => x.goal_completion_rate, show: (x) => `${pct(x.goal_completion_rate)} (${x.completed_goals}/${x.conversations})` },
    { label: "Objection Handling (0–3)", get: (x) => x.avg_objection_score, show: (x) => num(x.avg_objection_score) },
    { label: "Quality (1–5)", get: (x) => x.avg_quality_score, show: (x) => num(x.avg_quality_score) },
    { label: "Overall (0–5)", get: (x) => x.avg_overall_score, show: (x) => num(x.avg_overall_score) },
    { label: "Avg Latency", get: (x) => x.latency.avg_total_ms, show: (x) => ms(x.latency.avg_total_ms), lowerIsBetter: true },
    { label: "P95 Latency", get: (x) => x.latency.p95_total_ms, show: (x) => ms(x.latency.p95_total_ms), lowerIsBetter: true },
  ];
  return (
    <Card>
      <div className="mb-4 grid grid-cols-3 gap-4 border-b border-border pb-4">
        <Stat label="Conversations" value={summary.conversations} />
        <Stat label="Scenarios" value={summary.scenarios} />
        <Stat label="Prompt strategies" value={summary.prompt_variants} />
      </div>
      <div className="overflow-x-auto">
        <table className="tabular w-full min-w-[520px] text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-muted">
              <th className="py-2 pr-3 font-medium">Metric</th>
              {v.map((x) => (
                <th key={x.prompt_variant} className="px-3 py-2 font-medium">
                  <span className="inline-flex items-center gap-1.5">
                    <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: VARIANT_COLOR[x.prompt_variant] }} />
                    {VARIANT_LABEL[x.prompt_variant]}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const values = v.map((x) => r.get(x));
              const valid = values.filter((n): n is number => n !== null);
              const best = valid.length ? (r.lowerIsBetter ? Math.min(...valid) : Math.max(...valid)) : null;
              const allEqual = valid.length > 0 && valid.every((n) => n === valid[0]);
              return (
                <tr key={r.label} className="border-t border-border">
                  <td className="py-2.5 pr-3 text-muted">{r.label}</td>
                  {v.map((x, i) => {
                    const isBest = best !== null && values[i] === best && !allEqual;
                    return (
                      <td key={x.prompt_variant} className={`px-3 py-2.5 ${isBest ? "font-semibold text-ok" : ""}`}>
                        {r.show(x)}
                        {isBest && <span className="sr-only"> (best)</span>}
                        {isBest && <span aria-hidden> ▲</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted">
        ▲ marks the best value in a row. Differences of a few tenths of a point on {summary.scenarios} scenarios are
        not statistically meaningful.
      </p>
    </Card>
  );
}

function ChartLegend() {
  return <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} iconType="circle" />;
}

function ScoreChart({ variants }: { variants: VariantSummary[] }) {
  const metrics = [
    { metric: "Goal completion", value: (v: VariantSummary) => v.goal_completion_rate * 100, raw: (v: VariantSummary) => pct(v.goal_completion_rate) },
    { metric: "Objection handling", value: (v: VariantSummary) => ((v.avg_objection_score ?? 0) / 3) * 100, raw: (v: VariantSummary) => `${num(v.avg_objection_score)} / 3` },
    { metric: "Quality", value: (v: VariantSummary) => (v.avg_quality_score / 5) * 100, raw: (v: VariantSummary) => `${num(v.avg_quality_score)} / 5` },
    { metric: "Overall", value: (v: VariantSummary) => (v.avg_overall_score / 5) * 100, raw: (v: VariantSummary) => `${num(v.avg_overall_score)} / 5` },
  ];
  const data = metrics.map((m) => {
    const row: Record<string, string | number> = { metric: m.metric };
    variants.forEach((v) => {
      row[v.prompt_variant] = Number(m.value(v).toFixed(1));
      row[`${v.prompt_variant}_raw`] = m.raw(v);
    });
    return row;
  });
  return (
    <Card title="Scores by prompt strategy (% of maximum)">
      <div role="img" aria-label="Grouped bar chart of goal completion, objection handling, quality and overall score for each prompt strategy" className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ left: -10, right: 8, top: 8 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="metric" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
            <YAxis domain={[0, 100]} tick={AXIS} tickLine={false} axisLine={false} unit="%" />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: "var(--surface-2)" }}
              formatter={(value, name, item) => [
                `${(item.payload as Record<string, string>)[`${String(item.dataKey)}_raw`]} (${value}%)`,
                String(name),
              ]}
            />
            <ChartLegend />
            {variants.map((v) => (
              <Bar
                isAnimationActive={false}
                key={v.prompt_variant}
                dataKey={v.prompt_variant}
                name={VARIANT_LABEL[v.prompt_variant]}
                fill={VARIANT_COLOR[v.prompt_variant]}
                radius={[3, 3, 0, 0]}
                legendType="circle"
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function LatencyCard({ summary }: { summary: EvaluationSummary }) {
  const data = summary.by_variant.map((v) => ({
    name: VARIANT_LABEL[v.prompt_variant],
    "LLM (avg)": v.latency.avg_llm_ms ? Number(v.latency.avg_llm_ms.toFixed(1)) : 0,
    "TTS (avg)": v.latency.avg_tts_ms ? Number(v.latency.avg_tts_ms.toFixed(1)) : 0,
  }));
  return (
    <Card title="Latency per agent turn (ms)">
      <div role="img" aria-label="Stacked bar chart of average LLM and TTS latency for each prompt strategy" className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 20, right: 12 }}>
            <CartesianGrid stroke="var(--border)" horizontal={false} />
            <XAxis type="number" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
            <YAxis type="category" dataKey="name" tick={AXIS} tickLine={false} axisLine={false} width={70} />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "var(--surface-2)" }} formatter={(v) => `${v} ms`} />
            <ChartLegend />
            <Bar isAnimationActive={false} dataKey="LLM (avg)" stackId="a" fill="#6b8afd" />
            <Bar isAnimationActive={false} dataKey="TTS (avg)" stackId="a" fill="#9aa7bd" radius={[0, 3, 3, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="tabular mt-3 w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-muted">
            <th className="py-1.5 font-medium">Strategy</th>
            <th className="py-1.5 font-medium">Avg</th>
            <th className="py-1.5 font-medium">P50</th>
            <th className="py-1.5 font-medium">P95</th>
            <th className="py-1.5 font-medium">Turns</th>
          </tr>
        </thead>
        <tbody>
          {summary.by_variant.map((v) => (
            <tr key={v.prompt_variant} className="border-t border-border">
              <td className="py-1.5">{VARIANT_LABEL[v.prompt_variant]}</td>
              <td>{ms(v.latency.avg_total_ms)}</td>
              <td>{ms(v.latency.p50_total_ms)}</td>
              <td>{ms(v.latency.p95_total_ms)}</td>
              <td className="text-muted">{v.latency.samples}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        Simulated-benchmark latency: text input (no STT), server-side. Real voice latency is shown on the Voice Agent page.
      </p>
    </Card>
  );
}

const DIST_RANGE: Record<ScoreDistribution["metric"], number[]> = {
  goal: [0, 1, 2],
  objection: [0, 1, 2, 3],
  quality: [1, 2, 3, 4, 5],
};
const DIST_LABEL: Record<ScoreDistribution["metric"], string> = {
  goal: "Goal completion (0–2)",
  objection: "Objection handling (0–3)",
  quality: "Quality (1–5)",
};

function DistributionCard({
  distributions,
  metric,
  onMetric,
}: {
  distributions: ScoreDistribution[];
  metric: ScoreDistribution["metric"];
  onMetric: (m: ScoreDistribution["metric"]) => void;
}) {
  const variants = (["zero_shot", "few_shot", "persona"] as Variant[]).filter((v) => distributions.some((d) => d.prompt_variant === v));
  const data = DIST_RANGE[metric].map((score) => {
    const row: Record<string, number | string> = { score: String(score) };
    variants.forEach((v) => {
      row[v] = distributions.find((d) => d.metric === metric && d.prompt_variant === v && d.score === score)?.count ?? 0;
    });
    return row;
  });
  return (
    <Card
      title="Score distribution"
      action={
        <div role="tablist" aria-label="Metric" className="flex overflow-hidden rounded-md border border-border text-xs">
          {(Object.keys(DIST_LABEL) as ScoreDistribution["metric"][]).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={metric === m}
              onClick={() => onMetric(m)}
              className={`px-2.5 py-1 ${metric === m ? "bg-surface-2 font-medium" : "text-muted hover:bg-surface-2"}`}
            >
              {m === "goal" ? "Goal" : m === "objection" ? "Objection" : "Quality"}
            </button>
          ))}
        </div>
      }
    >
      <div role="img" aria-label={`Histogram of ${DIST_LABEL[metric]} scores per strategy`} className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ left: -20, right: 8, top: 8 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="score" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--border)" }} label={{ value: DIST_LABEL[metric], position: "insideBottom", offset: -2, fontSize: 11, fill: "var(--muted)" }} height={40} />
            <YAxis allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "var(--surface-2)" }} formatter={(v, n) => [`${v} conversations`, String(n)]} labelFormatter={(l) => `Score ${l}`} />
            <ChartLegend />
            {variants.map((v) => (
              <Bar isAnimationActive={false} key={v} dataKey={v} name={VARIANT_LABEL[v]} fill={VARIANT_COLOR[v]} radius={[3, 3, 0, 0]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function CategoryCard({ summary }: { summary: EvaluationSummary }) {
  const variants = summary.by_variant.map((v) => v.prompt_variant);
  const cats = [...new Set(summary.by_category.map((c) => c.group))];
  const data = cats.map((c) => {
    const row: Record<string, string | number> = { category: titleCase(c) };
    variants.forEach((v) => {
      const cell = summary.by_category.find((x) => x.group === c && x.prompt_variant === v);
      row[v] = cell ? Number(cell.avg_overall_score.toFixed(2)) : 0;
    });
    return row;
  });
  return (
    <Card title="Overall score by scenario category (0–5)">
      <div role="img" aria-label="Grouped horizontal bar chart of overall score per scenario category and strategy" className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 40, right: 12 }}>
            <CartesianGrid stroke="var(--border)" horizontal={false} />
            <XAxis type="number" domain={[0, 5]} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
            <YAxis type="category" dataKey="category" tick={AXIS} tickLine={false} axisLine={false} width={120} />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "var(--surface-2)" }} formatter={(v, n) => [v, String(n)]} />
            <ChartLegend />
            {variants.map((v) => (
              <Bar isAnimationActive={false} key={v} dataKey={v} name={VARIANT_LABEL[v]} fill={VARIANT_COLOR[v]} radius={[0, 3, 3, 0]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function Heatmap({ summary }: { summary: EvaluationSummary }) {
  const variants = summary.by_variant.map((v) => v.prompt_variant);
  const groups = summary.scenario_matrix.reduce<{ category: string; rows: ScenarioRow[] }[]>((acc, row) => {
    const last = acc[acc.length - 1];
    if (last && last.category === row.category) last.rows.push(row);
    else acc.push({ category: row.category, rows: [row] });
    return acc;
  }, []);
  return (
    <Card title="Scenario performance (overall score 0–5)">
      <div className="overflow-x-auto">
        <table className="tabular w-full min-w-[560px] border-separate border-spacing-y-1 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-muted">
              <th className="py-1 pr-3 font-medium">Scenario</th>
              <th className="px-2 py-1 font-medium">Diff.</th>
              {variants.map((v) => (
                <th key={v} className="px-2 py-1 text-center font-medium">
                  {VARIANT_LABEL[v]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => [
              <tr key={`h-${group.category}`}>
                <td colSpan={2 + variants.length} className="pt-3 text-xs font-semibold uppercase tracking-wide text-muted">
                  {titleCase(group.category)}
                </td>
              </tr>,
              ...group.rows.map((row) => (
                <tr key={row.scenario_id}>
                  <td className="py-1 pr-3">{row.scenario_name}</td>
                  <td className="px-2 text-muted">{row.difficulty}</td>
                  {variants.map((v) => {
                    const cell = row.cells.find((c) => c.prompt_variant === v);
                    if (!cell) return <td key={v} className="px-2 text-center text-muted">–</td>;
                    const goalMark = cell.goal_completion_score === 2 ? "✓" : cell.goal_completion_score === 1 ? "◐" : "✕";
                    return (
                      <td key={v} className="px-1">
                        <Link
                          href={`/conversations?id=${cell.conversation_id}`}
                          title={`Goal ${cell.goal_completion_score}/2 · Quality ${cell.conversation_quality_score}/5`}
                          className="block rounded-md px-2 py-1.5 text-center hover:ring-2 hover:ring-accent"
                          style={{ background: heat(cell.overall_score) }}
                        >
                          {cell.overall_score.toFixed(2)}{" "}
                          <span className="text-xs opacity-70" aria-label={`goal ${cell.goal_completion_score} of 2`}>
                            {goalMark}
                          </span>
                        </Link>
                      </td>
                    );
                  })}
                </tr>
              )),
            ])}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted">✓ goal achieved · ◐ partial · ✕ not achieved. Click a cell to open the conversation.</p>
    </Card>
  );
}

function FlagList({ title, items, empty, showLatency }: { title: string; items: Flag[]; empty: string; showLatency?: boolean }) {
  return (
    <Card title={title}>
      {items.length === 0 ? (
        <p className="text-sm text-muted">{empty}</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {items.map((f) => (
            <li key={f.conversation_id}>
              <Link href={`/conversations?id=${f.conversation_id}`} className="flex items-center justify-between gap-3 py-2 hover:text-accent">
                <span className="min-w-0 truncate">{f.scenario_name ?? "Live conversation"}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <VariantChip variant={f.prompt_variant} />
                  <span className="tabular w-16 text-right text-muted">
                    {showLatency ? ms(f.avg_total_latency_ms) : <Pill tone={f.goal_completion_score === 0 ? "danger" : "warn"}>{f.overall_score.toFixed(2)}</Pill>}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
