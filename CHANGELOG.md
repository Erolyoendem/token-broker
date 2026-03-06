# Changelog – TokenBroker

All notable changes to this project are documented here.

## [Unreleased]

- Group-Buy Stripe payment integration
- Configurable per-user token limits
- Extended monitoring/alerting

---

## [0.2.0] – TAB H – 2026-03-06

### Added
- Crowdfunding API endpoints: `POST /group-buys`, `POST /group-buys/{id}/join`, `GET /group-buys`, `GET /group-buys/{id}`
- Participant tracking with `group_buy_participants` table

## [0.1.9] – TAB G – 2026-03-06

### Added
- Crowdfunding foundation: `group_buys` Supabase table, `create_group_buy`, `join_group_buy`, `check_and_trigger` logic
- 4 passing tests for group-buy flows

## [0.1.8] – TAB E – 2026-03-06

### Changed
- `/chat` endpoint now authenticates via `X-TokenBroker-Key` header instead of query param

## [0.1.7] – TAB D – 2026-03-06

### Added
- `db_providers.py`: Supabase-backed provider list with `get_active_providers_from_db`
- `GET /providers` endpoint returns live provider config from DB
- Tests for DB-provider routing

## [0.1.6] – TAB C – 2026-03-06

### Added
- README.md with CI badge and live URL

## [0.1.5] – TAB B – 2026-03-06

### Added
- GitHub Actions CI workflow (`.github/workflows/ci.yml`)
- pytest-asyncio dependency

## [0.1.4] – TAB A – 2026-03-06

### Added
- DeepSeek provider (`deepseek-chat`, $0.14/$0.28 per 1M tokens)
- `call_with_fallback` logic: NVIDIA first, DeepSeek on failure
- Tests for fallback routing

## [0.1.3] – TAB 1 – 2026-03-06

### Added
- Discord webhook notifications on every `/chat` call (`discord.py`, `notify()`)
- Usage logging per user and provider

## [0.1.0] – Initial – 2026-03-06

### Added
- FastAPI app with `/health`, `/chat` endpoints
- NVIDIA provider (meta/llama-3.1-70b-instruct, free-tier)
- Railway deployment via Dockerfile + `railway.toml`
- Supabase DB integration (`db.py`)
- API key authentication (`auth.py`)
