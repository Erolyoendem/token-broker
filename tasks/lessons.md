# TokenBroker – Lessons Learned

Gesammelte Erkenntnisse aus der Entwicklung.

---


## Architecture

- **[2026-03-07]** APScheduler-Jobs immer im lifespan-Kontext starten, nicht als globale Module-Level-Objekte

## Supabase

- **[2026-03-07]** Supabase .single() wirft Fehler bei 0 Ergebnissen – immer .maybe_single() verwenden

## FastAPI

- **[2026-03-07]** Doppelte FastAPI-Routen entstehen durch append an main.py – immer prüfen ob Route bereits existiert

## Testing

- **[2026-03-07]** patch('module.CONSTANT') funktioniert nur wenn Modul explizit importiert ist, nicht über Pakete
