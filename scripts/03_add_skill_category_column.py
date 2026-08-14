"""
Task 2 migration: adds a skill_category column to `people`, which the n8n
automation will fill in via an LLM classification step.

Written as an idempotent migration (checks if the column already exists
before altering) rather than baking this into 02_build_database.py directly,
because 02_build_database.py drops and rebuilds the whole DB from the 3 raw
CSVs every run - it has no concept of "automation-assigned" data, and it
shouldn't need one. Keeping this as a separate, re-runnable step means
re-running Task 1's pipeline never wipes out tags Task 2 already assigned
elsewhere, and running this script twice is always safe.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "consultbae.db"


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(people)").fetchall()]

    if "skill_category" not in cols:
        conn.execute("ALTER TABLE people ADD COLUMN skill_category TEXT")
        print("Added people.skill_category")
    else:
        print("people.skill_category already exists, skipping")

    if "skill_category_tagged_at" not in cols:
        conn.execute("ALTER TABLE people ADD COLUMN skill_category_tagged_at TEXT")
        print("Added people.skill_category_tagged_at")
    else:
        print("people.skill_category_tagged_at already exists, skipping")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    migrate()
