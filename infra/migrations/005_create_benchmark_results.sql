-- Migration 005: benchmark_results table
-- Run in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS benchmark_results (
    id           BIGSERIAL PRIMARY KEY,
    task_id      TEXT NOT NULL,
    category     TEXT NOT NULL,
    provider     TEXT NOT NULL,
    passed       BOOLEAN NOT NULL,
    response     TEXT DEFAULT '',
    note         TEXT DEFAULT '',
    latency_s    FLOAT NOT NULL,
    tokens_used  INT DEFAULT 0,
    error        TEXT DEFAULT '',
    run_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bench_provider ON benchmark_results (provider);
CREATE INDEX IF NOT EXISTS idx_bench_category ON benchmark_results (category);
CREATE INDEX IF NOT EXISTS idx_bench_run_at   ON benchmark_results (run_at DESC);
