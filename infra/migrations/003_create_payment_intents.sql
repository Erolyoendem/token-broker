CREATE TABLE payment_intents (
  id SERIAL PRIMARY KEY,
  stripe_payment_intent_id TEXT UNIQUE NOT NULL,
  group_buy_id INTEGER REFERENCES group_buys(id),
  user_id UUID NOT NULL,
  amount BIGINT NOT NULL,   -- in Cent (z.B. 1000 für 10.00 €)
  status TEXT DEFAULT 'requires_payment_method',
  created_at TIMESTAMP DEFAULT NOW()
);
