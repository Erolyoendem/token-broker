#!/usr/bin/env python3
"""
tasks/skills/lesson.py – /lesson skill: adds an entry to tasks/lessons.md.

Usage (as a script):
    python tasks/skills/lesson.py "Stripe Webhooks müssen vor dem Test in Railway gesetzt sein"

Usage (as Claude skill – triggered via /lesson "Regel"):
    The skill reads the lesson text from argv[1] and appends it with timestamp.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

LESSONS_FILE = Path(__file__).parent.parent / "lessons.md"


def add_lesson(lesson: str, category: str = "General") -> str:
    ts = datetime.now().strftime("%Y-%m-%d")
    entry = f"- **[{ts}]** {lesson}\n"

    if not LESSONS_FILE.exists():
        LESSONS_FILE.write_text(
            "# TokenBroker – Lessons Learned\n\n"
            "Gesammelte Erkenntnisse aus der Entwicklung.\n\n"
            "---\n\n",
            encoding="utf-8",
        )

    content = LESSONS_FILE.read_text(encoding="utf-8")

    # Find or create category section
    header = f"## {category}"
    if header in content:
        # Append after header
        content = content.replace(header + "\n", header + "\n" + entry, 1)
    else:
        content = content + f"\n{header}\n\n{entry}"

    LESSONS_FILE.write_text(content, encoding="utf-8")
    return f"✓ Lesson added to {LESSONS_FILE}: {lesson}"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: lesson.py \"Deine Lektion\"  [Kategorie]")
        sys.exit(1)
    lesson = sys.argv[1]
    category = sys.argv[2] if len(sys.argv) > 2 else "General"
    print(add_lesson(lesson, category))


if __name__ == "__main__":
    main()
