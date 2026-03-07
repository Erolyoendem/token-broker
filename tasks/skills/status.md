# Skill: /status

## Befehl
```
python tasks/skills_cli.py status
```

## Was es tut
Gibt einen vollständigen Projekt-Statusbericht aus:
1. Railway Health-Check (`GET /health`)
2. Letzte 3 Git-Commits (`git log --oneline -3`)
3. Anzahl offener Tests (`pytest --collect-only -q | tail -1`)
4. Supabase-Tabellen-Check (group_buys, payment_intents, training_pairs)
5. Inhalt von `NEXT_SESSION.md` (erste 30 Zeilen)

## Erwartetes Ergebnis
```
[status] === TokenBroker Status ===
Railway:   ✓ https://yondem-production.up.railway.app → ok
Git:       d6f8298 [TAB A] Fix 500 bei /group-buys
           cc9c8d3 [TAB 11] Marktbeobachtungs-Agent
Tests:     ✓ 30 tests collected
DB:        ✓ group_buys, payment_intents, training_pairs
Next:      MVP 3: Vergleichsplattform
```
