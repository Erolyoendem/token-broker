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

## Nächste Schritte

1. Aufgaben-Queue (Redis/Celery) für verteilte Konvertierungen
2. Pro-Agent API-Keys in Supabase verwalten
3. Trainingsdaten-Export-Endpoint (`GET /training-data`)
4. Feintuning-Pipeline mit gesammelten Paaren
