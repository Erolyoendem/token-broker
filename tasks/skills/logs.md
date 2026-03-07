# Skill: /logs

## Befehl
```
python tasks/skills_cli.py logs [--tail N]
```

## Was es tut
1. Führt `railway logs --service yondem --tail N` aus (Standard: 50)
2. Filtert und hebt Fehler (ERROR, Exception, Traceback) farbig hervor
3. Gibt Zusammenfassung aus: X Errors, letzte Aktivität

## Optionen
- `--tail 100` → letzte 100 Zeilen
- `--errors-only` → nur Zeilen mit ERROR/Exception

## Erwartetes Ergebnis
```
[logs] Fetching Railway logs (tail=50)...
INFO:     GET /health → 200 OK
ERROR:    postgrest.exceptions.APIError: ...
[logs] Summary: 1 error found in last 50 lines
```
