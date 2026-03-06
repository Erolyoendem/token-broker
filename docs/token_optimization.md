# Token-Optimierung

## Übersicht

Dieses Dokument beschreibt die in TAB 6 durchgeführten Maßnahmen zur Reduzierung der Token-Kosten im TokenBroker-Backend.

## Analyse: System-Prompts in `providers.py`

Die `Provider.chat()`-Methode in `backend/app/providers.py` enthält **keine eigenen System-Prompts** – sie ist ein reiner Passthrough, der das `messages`-Array der aufrufenden Schicht direkt an die Provider-API weiterleitet.

**Empfehlung für Aufrufer:** System-Prompts in `/chat`- und `/v1/chat/completions`-Anfragen so kurz wie möglich halten. Statt ausführlicher Rollenbeschreibungen genügt z.B.:

```
# Vorher (redundant)
"Du bist ein hilfreicher Assistent. Beantworte alle Fragen präzise und klar.
Sei freundlich und vermeide unnötige Wiederholungen."

# Nachher (kompakt)
"Hilfreicher Assistent. Präzise, keine Wiederholungen."
```

Ein typischer System-Prompt von 50 Tokens → 10 Tokens spart bei 10.000 Anfragen/Tag **ca. 400.000 Input-Tokens/Tag**.

## Implementierung: Response-Cache in `router.py`

### Mechanismus

In `backend/app/router.py` wurde ein **In-Process-Dictionary-Cache** in `call_with_fallback()` ergänzt:

- **Cache-Key:** SHA-256-Hash des serialisierten `messages`-Arrays
- **TTL:** 300 Sekunden (5 Minuten)
- **Eviction:** Lazy – abgelaufene Einträge werden vor jedem Schreiben entfernt

### Code-Änderungen

```python
# Neue Konstanten und Cache-Dict
_CACHE_TTL = 300
_response_cache: dict[str, tuple[dict, Provider, float]] = {}

def _cache_key(messages: list[dict]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()

def _evict_expired() -> None:
    now = time.time()
    expired = [k for k, (_, _, ts) in _response_cache.items() if now - ts > _CACHE_TTL]
    for k in expired:
        del _response_cache[k]
```

Bei einem Cache-Hit in `call_with_fallback()` wird **kein API-Call** ausgeführt, wodurch alle tokens_used = 0 (aus Cache-Perspektive) sind.

### Einsatzszenarien mit hoher Ersparnis

| Szenario | Beispiel | Ersparnis |
|---|---|---|
| Wiederholte identische Anfragen | Gleicher Bot-Prompt in kurzer Zeit | 100 % der Tokens |
| Polling-Verhalten | Client fragt alle 5s mit gleichem Prompt | ~90 % Reduktion |
| Demo/Testing | Gleiche Anfragen in Entwicklung | 100 % |

### Einschränkungen

- Cache ist **nicht persistent** (Neustart leert ihn)
- Cache ist **pro Instanz** (kein Shared Cache bei Horizontal Scaling)
- Geeignet für **deterministische Prompts**; bei Konversationen mit wechselndem Kontext ist der Hit-Rate gering

### Skalierung auf Redis (optional)

Für Produktions-Setups mit mehreren Railway-Instanzen kann der Dict-Cache durch Redis ersetzt werden:

```python
import redis
r = redis.Redis.from_url(os.getenv("REDIS_URL"))

def get_cached(key):
    val = r.get(key)
    return json.loads(val) if val else None

def set_cached(key, data):
    r.setex(key, _CACHE_TTL, json.dumps(data))
```

## Test

```bash
cd /Users/haksystems/TokenBroker
python test_token_optimization.py
```

Erwartete Ausgabe:
```
=== Token Optimization Test ===
First call  : 30 tokens  (API calls made: 1)  ...ms
Second call : 30 tokens  (API calls made: 1)  ...ms
Cache hit   : YES
Tokens saved: 30 (100% on repeated identical prompts)
Cache TTL   : 300s

PASS: Second call served from cache, no API tokens consumed.
```

## Zusammenfassung

| Maßnahme | Einsparung | Aufwand |
|---|---|---|
| System-Prompt-Kürzung | ~80 % der Prompt-Tokens | Niedrig |
| Response-Cache (Dict, TTL 5 min) | 100 % bei Cache-Hit | Implementiert |
| Response-Cache (Redis, shared) | 100 % bei Cache-Hit, skalierbar | Optional |
