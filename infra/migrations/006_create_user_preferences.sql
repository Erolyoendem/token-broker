-- Migration 006: user_preferences table
-- Run in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id    TEXT PRIMARY KEY,
    preference TEXT NOT NULL DEFAULT 'balanced'
                   CHECK (preference IN ('accuracy','speed','cost','balanced')),
    task_type  TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
