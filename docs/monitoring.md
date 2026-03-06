# Monitoring – TokenBroker

## Übersicht

Das Skript `infra/monitor.py` prüft stündlich zwei Dinge:

1. **Health-Check** – GET `/health` gegen die produktive Railway-URL
2. **Token-Verbrauch** – Supabase-Abfrage der letzten 24 h; Alert bei zu hohem Verbrauch

Bei Problemen wird automatisch eine Discord-Nachricht über den bestehenden Webhook gesendet.

---

## Datei: `infra/monitor.py`

### Abhängigkeiten

| Paket          | Zweck                          |
|----------------|--------------------------------|
| `httpx`        | HTTP-Requests (health + Discord) |
| `python-dotenv`| `.env` aus `backend/.env` laden  |
| `supabase`     | Datenbank-Abfrage              |
| `APScheduler`  | Dauerbetrieb mit `--loop`      |

Alle Pakete sind in `backend/requirements.txt` enthalten.

### Env-Variablen

| Variable               | Pflicht | Default                                              |
|------------------------|---------|------------------------------------------------------|
| `DISCORD_WEBHOOK_URL`  | Ja      | –                                                    |
| `SUPABASE_URL`         | Ja      | –                                                    |
| `SUPABASE_ANON_KEY`    | Ja      | –                                                    |
| `HEALTH_URL`           | Nein    | `https://yondem-production.up.railway.app/health`    |
| `ALERT_TOKEN_THRESHOLD`| Nein    | `500000` (500k Tokens/24h)                           |

---

## Betriebsmodi

### Einmalig (One-Shot)

```bash
cd /pfad/zum/repo
python infra/monitor.py
```

Gibt Ergebnis in stdout aus, beendet sich danach. Ideal für GitHub Actions / klassischen Cron.

### Dauerbetrieb (APScheduler)

```bash
python infra/monitor.py --loop
```

Führt die Checks sofort einmal aus, dann stündlich. Mit `Ctrl+C` beenden.

---

## Automatisierung

### Option A: GitHub Actions (empfohlen)

Datei: `.github/workflows/monitor.yml`

```yaml
on:
  schedule:
    - cron: "0 * * * *"   # stündlich
  workflow_dispatch:        # manuell auslösbar
```

**Secrets konfigurieren** (Repository → Settings → Secrets → Actions):

| Secret                | Wert                    |
|-----------------------|-------------------------|
| `DISCORD_WEBHOOK_URL` | Discord-Webhook-URL     |
| `SUPABASE_URL`        | Supabase-Projekt-URL    |
| `SUPABASE_ANON_KEY`   | Supabase Anon Key       |

Manueller Test: GitHub → Actions → „Monitor" → „Run workflow".

### Option B: Systemd-Timer (Linux-Server)

```ini
# /etc/systemd/system/tokenbroker-monitor.service
[Unit]
Description=TokenBroker Monitor

[Service]
Type=oneshot
WorkingDirectory=/opt/token-broker
ExecStart=/opt/token-broker/backend/venv/bin/python infra/monitor.py
EnvironmentFile=/opt/token-broker/backend/.env
```

```ini
# /etc/systemd/system/tokenbroker-monitor.timer
[Unit]
Description=Stündlicher TokenBroker Monitor

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now tokenbroker-monitor.timer
```

### Option C: Klassischer Cron

```cron
0 * * * * cd /opt/token-broker && /opt/token-broker/backend/venv/bin/python infra/monitor.py >> /var/log/tokenbroker-monitor.log 2>&1
```

---

## Discord-Alerts

### Health-Check fehlgeschlagen

```
🔴 TokenBroker Health FAIL
URL: `https://yondem-production.up.railway.app/health`
HTTP 503 – ...
```

### Hoher Token-Verbrauch

```
⚠️ TokenBroker – High Token Usage Alert
Last 24 h: 623.450 tokens (threshold: 500.000)

By provider:
  • `deepseek`: 420.000
  • `nvidia`: 203.450

Top users:
  • `a1b2c3d4…`: 310.000
  • `e5f6g7h8…`: 180.000
```

---

## Schwellenwert anpassen

Den Alarm-Schwellenwert über die Env-Variable steuern:

```bash
# In .env oder GitHub Secret:
ALERT_TOKEN_THRESHOLD=1000000   # 1 Mio Token/24h
```

---

## Manueller Test

```bash
cd /pfad/zum/repo/backend
source venv/bin/activate
cd ..
python infra/monitor.py
```

Erwartete Ausgabe bei laufendem System:

```
==================================================
[monitor] 2026-03-06 14:00 UTC
==================================================
[health] OK    {'status': 'ok', 'service': 'TokenBroker'}
[usage]  24h total=12450  rows=8  by_provider={'nvidia': 9800, 'deepseek': 2650}
```
