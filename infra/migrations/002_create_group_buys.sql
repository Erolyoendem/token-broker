CREATE TABLE group_buys (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  target_tokens BIGINT NOT NULL,
  current_tokens BIGINT DEFAULT 0,
  price_per_token DECIMAL NOT NULL,      -- in Euro oder USD
  status TEXT DEFAULT 'pending',          -- pending, active, completed, cancelled
  provider TEXT NOT NULL,                  -- z.B. 'deepseek', 'openai'
  expires_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE group_buy_participants (
  id SERIAL PRIMARY KEY,
  group_buy_id INTEGER REFERENCES group_buys(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  tokens_ordered BIGINT NOT NULL,
  paid BOOLEAN DEFAULT false,
  created_at TIMESTAMP DEFAULT NOW()
);
