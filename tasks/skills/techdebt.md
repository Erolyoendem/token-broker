# Skill: /techdebt

## Befehl
```
python tasks/skills_cli.py techdebt
```

## Was es tut
1. Führt `radon cc backend/app/ -s -n C` aus (Cyclomatic Complexity, nur C+)
2. Führt `radon mi backend/app/ -s` aus (Maintainability Index)
3. Sucht mit `pylint backend/app/` nach Duplikaten und Code-Smells
4. Schreibt Bericht nach `docs/techdebt_report.md` mit Timestamp
5. Gibt Top-10-Probleme im Terminal aus

## Wann verwenden
- Wöchentlich um Code-Qualität zu überwachen
- Vor größeren Refactorings
- Als Grundlage für Sprint-Planung (welche Teile zuerst aufräumen)

## Erwartetes Ergebnis
```
[techdebt] Running radon (complexity)...
[techdebt] Running radon (maintainability)...
[techdebt] Running pylint...
[techdebt] Report saved → docs/techdebt_report.md

Top Issues:
  app/main.py:45  C (complexity=12)
  app/router.py:88  B (complexity=8)
```

## Abhängigkeiten
```
pip install radon pylint
```
Oder in `requirements.txt` eintragen (Dev-Dependency).
