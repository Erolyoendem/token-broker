# Skill: /context

## Befehl
```
python tasks/skills_cli.py context
```

## Was es tut
1. Führt `scripts/generate_context.py` aus (erzeugt `PROJECT_CONTEXT.md`)
2. Öffnet / zeigt `PROJECT_CONTEXT.md` im Terminal (paged via `less`)
3. Gibt Datei-Pfad und Zeitstempel der Generierung aus

## Wann verwenden
- Vor dem Start einer neuen Session, um den Projektstand zu verstehen
- Als Kontext-Datei für neue KI-Instanzen (Tab-Übergaben)
- Nach größeren Refactorings um den Überblick zu aktualisieren

## Erwartetes Ergebnis
```
[context] Generating PROJECT_CONTEXT.md...
[context] Done – 312 lines written
[context] Path: /Users/.../TokenBroker/PROJECT_CONTEXT.md
```

## Abhängigkeiten
- `scripts/generate_context.py` muss vorhanden sein
- Kein externes Package erforderlich (pure Python)
