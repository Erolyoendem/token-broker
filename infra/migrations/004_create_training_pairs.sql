-- Migration 004: training_pairs table
-- Run in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS training_pairs (
    id              BIGSERIAL PRIMARY KEY,
    pair_id         TEXT NOT NULL,
    source_lang     TEXT NOT NULL,
    target_lang     TEXT NOT NULL,
    source_code     TEXT NOT NULL,
    target_code     TEXT NOT NULL,
    source_url      TEXT DEFAULT '',
    tokens_used     INT DEFAULT 0,
    provider        TEXT DEFAULT '',
    quality_score   FLOAT DEFAULT 0.0,
    agent_ratings   JSONB,
    status          TEXT DEFAULT 'pending'
                        CHECK (status IN ('pending','accepted','rejected','review')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_training_pairs_pair_id ON training_pairs (pair_id);
CREATE INDEX IF NOT EXISTS idx_training_pairs_status  ON training_pairs (status);
