# TokenBroker – Developer Reference

Live API: https://yondem-production.up.railway.app

---

## Authentication

All endpoints (except `/health`, `/payment/config`, `/llm-matrix*`) require:

```
X-TokenBroker-Key: tb_...
```

Admin-only endpoints require:

```
X-Admin-Key: <ADMIN_API_KEY>
```

---

## Chat Endpoints

### `POST /chat`

Send a message and receive a response from the best available provider.

**Request body:**

```json
{
  "messages": [{"role": "user", "content": "Hello"}],
  "provider":   "nvidia",     // optional – force a specific provider
  "preference": "accuracy",   // optional – accuracy | speed | cost | balanced
  "task_type":  "math"        // optional – math | code_gen | code_convert | factual | creative
}
```

**Routing logic (priority order):**

1. `provider` set → use that provider directly
2. `preference` or `task_type` set → dynamic routing via benchmark matrix (`get_best_model`)
3. Neither set → cheapest-first routing (default)

**Response:**

```json
{
  "provider":    "nvidia",
  "model":       "meta/llama-3.1-70b-instruct",
  "tokens_used": 42,
  "routing":     "accuracy",
  "response":    { /* OpenAI-format */ }
}
```

---

### `POST /v1/chat/completions`

OpenAI-compatible endpoint. Accepts same `preference` and `task_type` fields.
Bearer token in `Authorization` header.

```bash
curl https://yondem-production.up.railway.app/v1/chat/completions \
  -H "Authorization: Bearer tb_..." \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is 17*23?"}],"preference":"accuracy","task_type":"math"}'
```

---

## Dynamic Routing – `preference` Parameter

| Value | Description |
|---|---|
| `accuracy` | Provider with highest benchmark pass-rate for the given task_type |
| `speed` | Provider with lowest average latency |
| `cost` | Cheapest provider (cost per 1M tokens) |
| `balanced` | Composite score: 40% accuracy + 30% speed + 30% cost (default) |

Routing falls back to cheapest-first if no benchmark data is available.

**Example – prefer accuracy for math tasks:**

```json
{ "messages": [...], "preference": "accuracy", "task_type": "math" }
```

**Example – prefer speed, any task:**

```json
{ "messages": [...], "preference": "speed" }
```

---

## User Preferences

Store a per-user default preference so clients don't need to send it every time.

### `GET /preferences/{user_id}`

Returns the stored preference for a user.

```json
{ "user_id": "u_abc", "preference": "balanced", "task_type": null }
```

### `PUT /preferences/{user_id}`

```json
{ "preference": "accuracy", "task_type": "code_gen" }
```

---

## LLM Benchmark Matrix

### `GET /llm-matrix`

Returns the current provider comparison matrix.

Query params:
- `category` – filter by task category (math, code_gen, code_convert, factual, creative)
- `refresh=true` – rebuild from stored results

```bash
curl https://yondem-production.up.railway.app/llm-matrix?category=math
```

### `GET /llm-matrix/tasks`

List all benchmark task definitions.

### `GET /llm-matrix/providers`

Aggregated accuracy + latency per provider from stored results.

---

## Running the Benchmark

```bash
# One-off run against live backend
cd backend
TOKENBROKER_URL=https://yondem-production.up.railway.app \
TOKENBROKER_KEY=tb_... \
python ../scripts/run_benchmark.py --providers nvidia deepseek

# Only run math tasks
python ../scripts/run_benchmark.py --tasks math_001 math_002 math_003
```

The benchmark also runs automatically every Monday at 02:00 UTC via APScheduler.

---

## Supabase Migrations

Run in order via Supabase SQL Editor:

| File | Table |
|---|---|
| `infra/migrations/002_create_group_buys.sql` | group_buys, group_buy_participants |
| `infra/migrations/003_create_payment_intents.sql` | payment_intents |
| `infra/migrations/004_create_training_pairs.sql` | training_pairs |
| `infra/migrations/005_create_benchmark_results.sql` | benchmark_results |
| `infra/migrations/006_create_user_preferences.sql` | user_preferences |

---

## Environment Variables (Railway)

| Variable | Required | Description |
|---|---|---|
| `SUPABASE_URL` | yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | yes | Supabase anon key |
| `NVIDIA_API_KEY` | yes | NVIDIA free-tier API key |
| `DEEPSEEK_API_KEY` | yes | DeepSeek API key |
| `STRIPE_SECRET_KEY` | yes | Stripe secret (`sk_test_…`) |
| `STRIPE_PUBLISHABLE_KEY` | yes | Stripe publishable key |
| `STRIPE_WEBHOOK_SECRET` | yes | Stripe webhook signing secret |
| `DISCORD_WEBHOOK_URL` | yes | Discord notifications |
| `ADMIN_API_KEY` | yes | Admin endpoint auth |
| `GITHUB_TOKEN` | optional | Raises GitHub API limit for crawler |
| `BENCHMARK_PROVIDERS` | optional | Comma-separated (default: `nvidia,deepseek`) |
| `TOKEN_LIMIT_DEFAULT` | optional | Per-user token limit (default: 1000000) |
