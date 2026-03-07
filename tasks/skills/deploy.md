# Skill: /deploy

## Befehl
```
python tasks/skills_cli.py deploy
```

## Was es tut
1. Führt `railway up --service yondem --detach` aus
2. Wartet bis der Build abgeschlossen ist (Railway-Logs pollen)
3. Prüft den Health-Endpunkt (`GET /health`) alle 5s, max. 120s
4. Gibt Status und letzten Deployment-Build-Link aus

## Wann verwenden
Nach Code-Änderungen, die direkt auf Railway deployed werden sollen –
ohne manuell `railway up` tippen zu müssen.

## Erwartetes Ergebnis
```
[deploy] Uploading to Railway...
[deploy] Waiting for health check...
[deploy] ✓ https://yondem-production.up.railway.app/health → {"status":"ok"}
[deploy] Done in 47s
```

## Fehlerfall
- Timeout nach 120s → Exit-Code 1, Fehlermeldung mit Build-Log-URL
- Health-Check schlägt fehl → zeigt letzten Railway-Log-Ausschnitt
