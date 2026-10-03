-- =============================================================================
-- Hinglish Voice Sales Agent: analysis queries (PostgreSQL)
--
-- Run all of them:   psql "$DATABASE_URL_PSQL" -f sql/analysis.sql
-- (use a plain postgresql:// URL for psql, i.e. without the "+psycopg" driver suffix)
--
-- Views used (created by Alembic migration 0002):
--   conversation_results    one row per evaluated conversation: scores + scenario + mean latency
--   turn_latencies          one row per agent turn with STT / LLM / TTS / total latency
--   latest_benchmark_run    the newest benchmark run with results (real runs win over mock)
--
-- Every query targets that latest run. To analyse a specific run, replace
--   (SELECT id FROM latest_benchmark_run)
-- with a literal run id. NOTE: if the latest run used mock providers, every number below
-- comes from the rule-based mock stack and says nothing about real model quality.
--
-- Latency caveat: benchmark latency is simulated-benchmark latency (text input, no STT).
-- Live voice latency is stored with source = 'voice' and is excluded from these queries.
-- =============================================================================


-- 0. Which run is being analysed, and is it mock or real?
SELECT r.id, r.run_mode, r.status, r.total_conversations, r.completed_conversations,
       r.failed_conversations, r.started_at
FROM benchmark_runs r
WHERE r.id = (SELECT id FROM latest_benchmark_run);


-- 1. Average overall score by prompt strategy
SELECT prompt_variant,
       count(*)                          AS conversations,
       round(avg(overall_score), 2)      AS avg_overall_score
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant
ORDER BY avg_overall_score DESC;


-- 2. Goal completion rate by prompt strategy (goal_completion_score = 2 means achieved)
SELECT prompt_variant,
       count(*)                                              AS conversations,
       count(*) FILTER (WHERE goal_completion_score = 2)     AS goals_achieved,
       round(100.0 * count(*) FILTER (WHERE goal_completion_score = 2) / count(*), 1)
                                                             AS goal_completion_rate_pct,
       round(avg(goal_completion_score), 2)                  AS avg_goal_score_0_to_2
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant
ORDER BY goal_completion_rate_pct DESC;


-- 3. Objection handling by prompt strategy (NULL scores = no objection raised, excluded)
SELECT prompt_variant,
       count(objection_handling_score)                  AS conversations_with_objection,
       round(avg(objection_handling_score), 2)          AS avg_objection_score_0_to_3,
       count(*) FILTER (WHERE objection_handling_score >= 2) AS reasonable_or_strong
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant
ORDER BY avg_objection_score_0_to_3 DESC NULLS LAST;


-- 4. Conversation quality by prompt strategy
SELECT prompt_variant,
       round(avg(conversation_quality_score), 2)  AS avg_quality_1_to_5,
       min(conversation_quality_score)            AS min_quality,
       max(conversation_quality_score)            AS max_quality,
       count(*) FILTER (WHERE invented_claims)    AS conversations_with_invented_claims
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant
ORDER BY avg_quality_1_to_5 DESC;


-- 5. Average latency by prompt strategy (per agent turn, milliseconds)
--    stt_ms is NULL in benchmark runs because customer input is text.
SELECT prompt_variant,
       count(*)                                   AS agent_turns,
       round(avg(stt_latency_ms)::numeric, 1)     AS avg_stt_ms,
       round(avg(llm_latency_ms)::numeric, 1)     AS avg_llm_ms,
       round(avg(tts_latency_ms)::numeric, 1)     AS avg_tts_ms,
       round(avg(total_latency_ms)::numeric, 1)   AS avg_total_ms
FROM turn_latencies
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant
ORDER BY avg_total_ms;


-- 6. P50 (median) latency by prompt strategy
SELECT prompt_variant,
       round((percentile_cont(0.50) WITHIN GROUP (ORDER BY llm_latency_ms))::numeric, 1)   AS p50_llm_ms,
       round((percentile_cont(0.50) WITHIN GROUP (ORDER BY total_latency_ms))::numeric, 1) AS p50_total_ms
FROM turn_latencies
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant
ORDER BY p50_total_ms;


-- 7. P95 latency by prompt strategy
SELECT prompt_variant,
       round((percentile_cont(0.95) WITHIN GROUP (ORDER BY llm_latency_ms))::numeric, 1)   AS p95_llm_ms,
       round((percentile_cont(0.95) WITHIN GROUP (ORDER BY total_latency_ms))::numeric, 1) AS p95_total_ms
FROM turn_latencies
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant
ORDER BY p95_total_ms;


-- 8. Performance by scenario (all three strategies side by side)
SELECT scenario_id, scenario_name, category, difficulty,
       round(avg(overall_score), 2)                                         AS avg_overall,
       round(avg(overall_score) FILTER (WHERE prompt_variant = 'zero_shot'), 2) AS zero_shot,
       round(avg(overall_score) FILTER (WHERE prompt_variant = 'few_shot'), 2)  AS few_shot,
       round(avg(overall_score) FILTER (WHERE prompt_variant = 'persona'), 2)   AS persona
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY scenario_id, scenario_name, category, difficulty
ORDER BY avg_overall ASC;


-- 9. Performance by scenario difficulty
SELECT difficulty, prompt_variant,
       count(*)                                                       AS conversations,
       round(avg(overall_score), 2)                                   AS avg_overall,
       round(100.0 * count(*) FILTER (WHERE goal_completion_score = 2) / count(*), 1)
                                                                      AS goal_completion_rate_pct
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY difficulty, prompt_variant
ORDER BY difficulty, prompt_variant;


-- 10. Performance by scenario category
SELECT category, prompt_variant,
       count(*)                                                       AS conversations,
       round(avg(overall_score), 2)                                   AS avg_overall,
       round(avg(objection_handling_score), 2)                        AS avg_objection,
       round(100.0 * count(*) FILTER (WHERE goal_completion_score = 2) / count(*), 1)
                                                                      AS goal_completion_rate_pct
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY category, prompt_variant
ORDER BY category, prompt_variant;


-- 11. Prompt x scenario matrix (overall score per cell)
SELECT scenario_id, category, difficulty,
       max(overall_score) FILTER (WHERE prompt_variant = 'zero_shot') AS zero_shot,
       max(overall_score) FILTER (WHERE prompt_variant = 'few_shot')  AS few_shot,
       max(overall_score) FILTER (WHERE prompt_variant = 'persona')   AS persona
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY scenario_id, category, difficulty
ORDER BY category, difficulty, scenario_id;


-- 12. Failure cases: goal not achieved at all, or weak overall score
SELECT conversation_id, prompt_variant, scenario_id, goal_completion_score,
       objection_handling_score, conversation_quality_score, overall_score,
       left(reasoning, 160) AS reasoning_excerpt
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
  AND (goal_completion_score = 0 OR overall_score < 2.5)
ORDER BY overall_score ASC, scenario_id;


-- 13. High-latency conversations (top 10 by mean per-turn total latency)
SELECT conversation_id, prompt_variant, scenario_id,
       round(avg_total_latency_ms::numeric, 1) AS avg_total_latency_ms,
       agent_turns
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
  AND avg_total_latency_ms IS NOT NULL
ORDER BY avg_total_latency_ms DESC
LIMIT 10;


-- 14. Number of completed demos (conversations where the goal was achieved)
SELECT prompt_variant,
       count(*) FILTER (WHERE goal_completed)      AS completed_demos,
       count(*)                                    AS conversations
FROM conversations
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant
ORDER BY completed_demos DESC;


-- 15. Distribution of scores (histogram per metric and strategy)
SELECT 'goal_completion' AS metric, prompt_variant, goal_completion_score AS score, count(*) AS conversations
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant, goal_completion_score
UNION ALL
SELECT 'objection_handling', prompt_variant, objection_handling_score, count(*)
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
  AND objection_handling_score IS NOT NULL
GROUP BY prompt_variant, objection_handling_score
UNION ALL
SELECT 'conversation_quality', prompt_variant, conversation_quality_score, count(*)
FROM conversation_results
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant, conversation_quality_score
ORDER BY metric, prompt_variant, score;


-- 16. How conversations ended, by strategy
SELECT prompt_variant, stop_reason, count(*) AS conversations
FROM conversations
WHERE benchmark_run_id = (SELECT id FROM latest_benchmark_run)
GROUP BY prompt_variant, stop_reason
ORDER BY prompt_variant, conversations DESC;


-- 17. Live voice latency (real end-to-end pipeline: STT + LLM + TTS), kept separate
SELECT run_mode,
       count(*)                                                       AS voice_turns,
       round(avg(stt_latency_ms)::numeric, 1)                         AS avg_stt_ms,
       round(avg(llm_latency_ms)::numeric, 1)                         AS avg_llm_ms,
       round(avg(tts_latency_ms)::numeric, 1)                         AS avg_tts_ms,
       round(avg(total_latency_ms)::numeric, 1)                       AS avg_total_ms,
       round((percentile_cont(0.95) WITHIN GROUP (ORDER BY total_latency_ms))::numeric, 1) AS p95_total_ms
FROM turn_latencies
WHERE source = 'voice'
GROUP BY run_mode;
