# TokenBroker – Agenten-Schwarm-Konzept

## Idee

Mehrere Goose-Instanzen laufen parallel und verarbeiten Aufgaben (z.B. Code-Konvertierungen)
über den TokenBroker-Proxy. Der Proxy optimiert Kosten, loggt alles zentral und sammelt
Trainingsdaten für späteres Feintuning.

## Architektur

```
┌─────────────────────────────────────────────────────────┐
│                    KUNDE / AUFTRAGGEBER                  │
│           (Code verlässt nie deren Infrastruktur)        │
└──────────────────────┬──────────────────────────────────┘
                       │ Aufgaben-Queue
                       ▼
┌─────────────────────────────────────────────────────────┐
│               TOKENBROKER PROXY (Railway)                │
│  POST /v1/chat/completions   POST /chat                  │
│  Router: NVIDIA (gratis) → DeepSeek (Fallback)          │
│  Auth: X-TokenBroker-Key   Token-Tracking: Supabase     │
└──────┬──────────────────────────────────────┬───────────┘
       │                                      │
       ▼                                      ▼
┌─────────────┐  ┌─────────────┐      ┌──────────────────┐
│  Goose #1   │  │  Goose #2   │ ...  │   Goose #N       │
│ (converter) │  │ (converter) │      │  (converter)      │
└──────┬──────┘  └──────┬──────┘      └──────┬───────────┘
       │                │                    │
       └────────────────┴────────────────────┘
                        │ Ergebnisse
                        ▼
┌─────────────────────────────────────────────────────────┐
│                   LOGGING & STORAGE                      │
│  Discord #tokenbroker-logs  │  Supabase token_usage     │
│  results.csv (lokal)        │  Ruby↔Python Trainingsdata│
└─────────────────────────────────────────────────────────┘
```

## Parallele Konvertierungen (5 Goose-Instanzen)

```bash
# Start 5 parallele Konvertierungen
for i in 1 2 3 4 5; do
  TOKENBROKER_KEY=tkb_agent_$i python run_conversion.py &
done
wait
```

Jede Instanz bekommt einen eigenen API-Key → separates Token-Tracking pro Agent.

## Zentrales Logging

Jeder `/chat`-Call sendet automatisch:
- Discord: `📨 TokenBroker | user: tkb_agent_1 | tokens: 364`
- Supabase: `token_usage` Tabelle (user_id, tokens, provider, timestamp)

## Trainingsdaten sammeln

Jedes Ruby↔Python-Paar wird als Trainingsdatensatz gespeichert:
```json
{"input": "<ruby_code>", "output": "<python_code>", "model": "llama-3.1-70b", "tokens": 364}
```

Ziel: 10.000 Paare → Feintuning eines kleineren Modells für günstigere Konvertierungen.

## Geschäftsmodell: Miet-Agenten

- Unternehmen mieten den Schwarm für Code-Migrationen
- Code verlässt nie deren Infrastruktur (on-premise Goose + eigener TokenBroker-Key)
- Abrechnung: pro Token (50% Marge via Großeinkauf/Crowdfunding)
- Anwendungsfälle: Ruby→Python, COBOL→Python, Legacy-Code-Dokumentation

## Praktischer Prototyp – Erfahrungen (agent_swarm.py)

### Implementierung

**`agent_swarm.py`** im Hauptverzeichnis nutzt `asyncio` + `aiohttp`:

- **5 parallele Worker** als asyncio-Tasks (keine separaten Prozesse noetig –
  IO-bound Workload profitiert vollstaendig von async Concurrency)
- **`asyncio.Queue`** verteilt Ruby-Dateien an freie Worker
- **Discord-Webhook** loggt jede Konvertierung + Abschluss-Zusammenfassung
- **`swarm_results.json`** speichert alle Ergebnisse strukturiert

```bash
# Ausfuehren (venv aktivieren):
python agent_swarm.py [--input-dir swarm_input] [--workers 5]
```

### Testergebnisse (2026-03-07)

| Metrik           | Wert                    |
|------------------|-------------------------|
| Dateien          | 11 Ruby-Dateien         |
| Erfolgreich      | 11 / 11 (100%)          |
| Token gesamt     | 3.078                   |
| Gesamtlaufzeit   | 5,89 s                  |
| Throughput       | ~522 Token/s            |
| Agenten          | 5 parallele Worker      |
| Proxy            | Railway (NVIDIA-backend)|

Sequenziell waere dieselbe Arbeit ca. 5x langsamer gewesen (~25–30 s).
Der Proxy hat alle Anfragen problemlos verarbeitet – kein Rate-Limit, keine Fehler.

### Konvertierte Dateien

`calculator.rb`, `calculator2.rb`, `bank_account.rb`, `fibonacci.rb`,
`hello.rb`, `hello2.rb`, `linked_list.rb`, `roman.rb`, `stack.rb`,
`user.rb`, `word_count.rb`

### Erkenntnisse

- **asyncio reicht aus**: Fuer IO-bound LLM-Calls sind asyncio-Tasks gleichwertig
  zu Subprozessen, aber deutlich leichter zu orchestrieren.
- **Queue-Modell skaliert**: Mehr Dateien = gleiche Struktur, nur laengere Laufzeit.
  Mehr Worker = hoehere Parallelitaet bis zum Rate-Limit des Proxys.
- **Discord-Logging funktioniert**: Jede Konvertierung erscheint in Echtzeit im
  Discord-Channel.
- **Fehlerbehandlung bewaehrt**: Einzelne API-Fehler stoppen keine anderen Worker.

## Naechste Schritte

1. Aufgaben-Queue (Redis/Celery) fuer verteilte Konvertierungen auf mehreren Maschinen
2. Pro-Agent API-Keys in Supabase verwalten (separates Token-Tracking)
3. Trainingsdaten-Export-Endpoint (`GET /training-data`)
4. Feintuning-Pipeline mit gesammelten Ruby/Python-Paaren
5. Worker-Count automatisch an Token-Budget und Rate-Limits anpassen
