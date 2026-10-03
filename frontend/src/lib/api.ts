// Typed client for the FastAPI backend. Types mirror backend/app/schemas.py.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Variant = "zero_shot" | "few_shot" | "persona";

export interface Latency {
  stt_ms: number | null;
  llm_ms: number | null;
  tts_ms: number | null;
  total_ms: number;
}

export interface Component {
  provider: string;
  model: string;
  mock: boolean;
  client_side?: boolean;
}

export interface AppConfig {
  components: { llm: Component; stt: Component; tts: Component };
  mock_components: ("stt" | "llm" | "tts")[];
  is_mock: boolean;
  llm_is_mock: boolean;
  prompt_variants: { id: Variant; title: string; description: string }[];
  limits: { max_audio_bytes: number };
}

export interface VoiceResponse {
  conversation_id: string;
  transcript: string;
  response_text: string;
  audio_url: string | null;
  latency: Latency;
  warnings: string[];
  mock_mode: boolean;
  mock_components: string[];
  speak_client_side: boolean;
}

export interface Scenario {
  id: string;
  name: string;
  category: string;
  description: string;
  customer_profile: string;
  initial_message: string;
  goal: string;
  completion_criteria: string[];
  expected_objection: string | null;
  difficulty: number;
}

export interface Turn {
  id: number;
  turn_number: number;
  speaker: "customer" | "agent";
  text: string;
  latency_ms: number | null;
  latency: Latency | null;
}

export interface Evaluation {
  goal_completion_score: number;
  objection_handling_score: number | null;
  conversation_quality_score: number;
  overall_score: number;
  invented_claims: boolean;
  reasoning: string;
  judge_model: string;
}

export interface ConversationDetail {
  id: string;
  prompt_variant: Variant;
  prompt_hash: string;
  source: "voice" | "benchmark";
  run_mode: "mock" | "real";
  llm_model: string | null;
  stop_reason: string | null;
  started_at: string;
  goal_completed: boolean | null;
  scenario: Scenario | null;
  turns: Turn[];
  evaluation: Evaluation | null;
  latency_summary: Latency | null;
}

export interface ConversationItem {
  id: string;
  prompt_variant: Variant;
  source: "voice" | "benchmark";
  run_mode: "mock" | "real";
  scenario_id: string | null;
  scenario_name: string | null;
  category: string | null;
  difficulty: number | null;
  goal_completed: boolean | null;
  stop_reason: string | null;
  goal_completion_score: number | null;
  objection_handling_score: number | null;
  conversation_quality_score: number | null;
  overall_score: number | null;
  avg_total_latency_ms: number | null;
  turn_count: number;
  started_at: string;
}

export interface ConversationList {
  items: ConversationItem[];
  total: number;
}

export interface RunInfo {
  id: string;
  status: string;
  run_mode: "mock" | "real";
  total_conversations: number;
  completed_conversations: number;
  failed_conversations: number;
  error: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface BenchmarkStatus {
  llm_provider: string;
  models: Record<string, string>;
  is_running: boolean;
  scenario_count: number;
  variants: Variant[];
  latest_run: RunInfo | null;
  runs: RunInfo[];
}

export interface LatencyStats {
  avg_total_ms: number | null;
  p50_total_ms: number | null;
  p95_total_ms: number | null;
  avg_llm_ms: number | null;
  avg_tts_ms: number | null;
  avg_stt_ms: number | null;
  samples: number;
}

export interface VariantSummary {
  prompt_variant: Variant;
  conversations: number;
  goal_completion_rate: number;
  avg_goal_score: number;
  avg_objection_score: number | null;
  objection_samples: number;
  avg_quality_score: number;
  avg_overall_score: number;
  completed_goals: number;
  invented_claims_count: number;
  latency: LatencyStats;
}

export interface GroupedScore {
  group: string;
  prompt_variant: Variant;
  conversations: number;
  avg_overall_score: number;
  goal_completion_rate: number;
}

export interface MatrixCell {
  prompt_variant: Variant;
  overall_score: number;
  goal_completion_score: number;
  objection_handling_score: number | null;
  conversation_quality_score: number;
  conversation_id: string;
}

export interface ScenarioRow {
  scenario_id: string;
  scenario_name: string;
  category: string;
  difficulty: number;
  cells: MatrixCell[];
}

export interface ScoreDistribution {
  metric: "goal" | "objection" | "quality";
  prompt_variant: Variant;
  score: number;
  count: number;
}

export interface Flag {
  conversation_id: string;
  prompt_variant: Variant;
  scenario_id: string | null;
  scenario_name: string | null;
  overall_score: number;
  goal_completion_score: number;
  avg_total_latency_ms: number | null;
}

export interface EvaluationSummary {
  benchmark_run: RunInfo | null;
  run_mode: "mock" | "real" | null;
  is_mock: boolean;
  available_modes: ("mock" | "real")[];
  conversations: number;
  scenarios: number;
  prompt_variants: number;
  by_variant: VariantSummary[];
  by_category: GroupedScore[];
  by_difficulty: GroupedScore[];
  scenario_matrix: ScenarioRow[];
  distributions: ScoreDistribution[];
  failure_cases: Flag[];
  high_latency: Flag[];
  latency_note: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    let code: string | undefined;
    try {
      const body = await res.json();
      message = body?.error?.message ?? message;
      code = body?.error?.code;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, res.status, code);
  }
  return res.json() as Promise<T>;
}

export async function apiGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${API_URL}${path}`);
  Object.entries(params ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  });
  try {
    return await parse<T>(await fetch(url, { cache: "no-store" }));
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError("Cannot reach the API. Is the backend running?", 0, "network");
  }
}

export async function apiPost<T>(path: string, body?: BodyInit | object): Promise<T> {
  const isForm = body instanceof FormData;
  try {
    return await parse<T>(
      await fetch(`${API_URL}${path}`, {
        method: "POST",
        headers: body && !isForm ? { "Content-Type": "application/json" } : undefined,
        body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
      }),
    );
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError("Cannot reach the API. Is the backend running?", 0, "network");
  }
}

export function audioSrc(path: string): string {
  return path.startsWith("http") ? path : `${API_URL}${path}`;
}
