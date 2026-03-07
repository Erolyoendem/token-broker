# Skill: /test

## Befehl
```
python tasks/skills_cli.py test [--module MODULE]
```

## Was es tut
1. Aktiviert das venv (`backend/venv`)
2. Führt `pytest backend/tests/ -v` aus (oder spezifisches Modul)
3. Zeigt Zusammenfassung: X passed / Y failed
4. Bei Fehlern: zeigt die ersten 20 Zeilen des Tracebacks

## Optionen
- `--module crowdfunding` → nur `tests/test_crowdfunding.py`
- `--module payment` → nur `tests/test_payment.py`
- (ohne Flag) → alle Tests

## Erwartetes Ergebnis
```
[test] Running pytest backend/tests/ ...
[test] ✓ 16 passed in 3.4s
```

## Fehlerfall
```
[test] ✗ 2 failed, 14 passed
[test] See full output above
```
