# Crowdfunding Flow – Testergebnisse

**Datum:** 2026-03-07  
**API:** https://yondem-production.up.railway.app  
**API-Key:** tkb_test_123  
**Ergebnis:** 5/5 PASSED

## Schritte

| # | Schritt | Endpoint | Status | Detail |
|---|---------|----------|--------|--------|
| 1 | Sammelbestellung anlegen | POST /group-buys | ✅ 200 | id=5, status=pending |
| 2 | Aktive Bestellungen abrufen | GET /group-buys | ✅ 200 | id=5 in Liste enthalten |
| 3 | Teilnehmer beitreten | POST /group-buys/5/join | ✅ 200 | current_tokens=100, status=active (Ziel erreicht) |
| 4 | Trigger manuell auslösen | POST /group-buys/5/trigger | ✅ 200 | status=active (bereits aktiv) |
| 5 | Details + Teilnehmerliste | GET /group-buys/5 | ✅ 200 | 1 Teilnehmer, paid=false |

## Beobachtungen

- Ziel (100 Tokens) wurde beim Join sofort erreicht → Status automatisch auf `active` gesetzt
- APScheduler-Trigger läuft parallel im Hintergrund (alle 5 min)
- Supabase-Tabellen `group_buys` und `group_buy_participants` sind live
- Teilnehmer erscheint korrekt in der Detailansicht
- `paid=false` korrekt – Stripe-Webhook noch nicht final konfiguriert
