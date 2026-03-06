-- TokenBroker Supabase Schema – MVP 1

CREATE TABLE providers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    input_price_per_million NUMERIC,
    output_price_per_million NUMERIC,
    cache_discount NUMERIC DEFAULT 0,
    active BOOLEAN DEFAULT true,
    api_base TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE token_usage (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    tokens_used INTEGER NOT NULL,
    provider TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW()
);
