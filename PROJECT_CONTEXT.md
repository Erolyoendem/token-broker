# TokenBroker – Project Context
Generated: 2026-03-07 15:05 UTC  |  Branch: `main`

## Quick Links
- Railway: https://yondem-production.up.railway.app
- GitHub:  https://github.com/Erolyoendem/token-broker
- Supabase: https://igbejdddgbvmgiankuev.supabase.co

## Recent Commits
```
5cdb993 [TAB 23] Add missing scripts package – fix app startup crash
ec1b9ac fix: add /swarm/submit, /swarm/status, /swarm/result endpoints
14bc825 [TAB 21] Erweitertes Agenten-Monitoring mit Alarmen und Dashboard
ecca866 [TAB 18] Dynamisches Modell-Routing basierend auf LLM-Matrix
2f00617 [TAB 20] Agenten-Training mit synthetischen Daten
94b6cef [TAB 15] Selbst-evolvierende Prompts mit Thompson Sampling
4ae6020 [TAB 16] Reinforcement Learning fuer Agenten (DQN)
ce6501b [TAB 15] Selbst-evolvierende Prompts mit Thompson Sampling
```

## Working Tree
```
M backend/app/main.py
 M test_conversions/calculator.py
 M test_conversions/user.py
?? backend/crowdfunding_test.log
?? backend/cto_agent/
?? backend/evolution/metrics.db
?? infra/bug_fixer.py
?? scripts/generate_context.py
?? tasks/
```

## Backend Modules (`backend/app/`)
- `backend/app/__init__.py`  (0 lines)
- `backend/app/auth.py`  (20 lines)
- `backend/app/crowdfunding.py`  (59 lines)
- `backend/app/db.py`  (18 lines)
- `backend/app/db_providers.py`  (21 lines)
- `backend/app/discord.py`  (17 lines)
- `backend/app/main.py`  (752 lines)
- `backend/app/metrics.py`  (31 lines)
- `backend/app/payment.py`  (98 lines)
- `backend/app/providers.py`  (54 lines)
- `backend/app/router.py`  (189 lines)
- `backend/app/swarm.py`  (52 lines)
- `backend/app/tenant/__init__.py`  (0 lines)
- `backend/app/tenant/deployment.py`  (54 lines)
- `backend/app/tenant/isolation.py`  (50 lines)
- `backend/app/tenant/resource_manager.py`  (70 lines)
- `backend/app/trigger.py`  (50 lines)
- `backend/app/usage.py`  (32 lines)

## Test Files
- `backend/tests/__init__.py`
- `backend/tests/test_agent_monitor.py`
- `backend/tests/test_agent_swarm.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_crowdfunding.py`
- `backend/tests/test_crowdfunding_api.py`
- `backend/tests/test_crowdfunding_flow.py`
- `backend/tests/test_db_providers.py`
- `backend/tests/test_enterprise.py`
- `backend/tests/test_evolution.py`
- `backend/tests/test_fallback.py`
- `backend/tests/test_health.py`
- `backend/tests/test_llm_benchmark.py`
- `backend/tests/test_market_intelligence.py`
- `backend/tests/test_offline_training.py`
- `backend/tests/test_onboarding.py`
- `backend/tests/test_payment.py`
- `backend/tests/test_prompt_optimizer.py`
- `backend/tests/test_rl_agent.py`
- `backend/tests/test_router_dynamic.py`
- `backend/tests/test_stats.py`
- `backend/tests/test_tenant_isolation.py`
- `backend/tests/test_training_pipeline.py`
- `backend/tests/test_trigger.py`

## Available Skills (`/skill`)
`/context`, `/deploy`, `/logs`, `/status`, `/techdebt`, `/test`

## Next Session Notes

# Next Session – TokenBroker

## Deployment Status (2026-03-06)

| Feld                | Wert |
|---------------------|------|
| Deployment ID       | 3a492c8e-30fa-48c1-bdfc-7b961887666e |
| Status              | SUCCESS |
| URL                 | https://yondem-production.up.railway.app |
| Health              | `{"status":"ok","service":"TokenBroker"}` |
| Environment         | production |
| Service             | yondem |

## Env-Variablen (gesetzt)

- `DEEPSEEK_API_KEY` — gesetzt am 2026-03-06
- `DISCORD_WEBHOOK_URL` — Discord-Benachrichtigungen aktiv
- `NVIDIA_API_KEY` — vorhanden (free-tier)
- `SUPABASE_*` — DB-Verbindung aktiv

## Abgeschlossene Tabs (Git-History)

| Tag   | Commit     | Beschreibung |
|-------|------------|--------------|
| TAB 1 | `9370ba0`  | Discord-Logging im /chat Endpunkt |
| TAB A | `c7d5ca5`  | DeepSeek-Fallback + Tests |
| TAB B | `21bcd95`  | CI-Workflow (GitHub Actions) |
| TAB C | `34c4e53`  | README + CI-Badge |
| TAB D | `d48f9d6`  | DB-Providers: Supabase-Router + Tests |
| TAB E | `796a997`  | Auth: X-TokenBroker-Key Header |
| TAB G | `67f4ea1`  | MVP 2: Crowdfunding-Grundgerüst (group_buys, 4 Tests) |
| TAB H | `a81215a`  | Crowdfunding-API-Endpunkte |
| TAB 4 | *(pending)* | Payment-Doku und Frontend-Skizze |

## Provider-Konfiguration

- **NVIDIA** – meta/llama-3.1-70b-instruct – kostenlos (free-tier credits), primärer Provider
- **DeepSeek** – deepseek-chat – $0.14/$0.28 per 1M tokens, Fallback

## Offene Punkte / nächste Schritte
