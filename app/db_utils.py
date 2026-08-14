"""
Task 3 — database integration.

This is what makes the audio app connect to the SAME database Task 1 built,
rather than being a disconnected feature. On every submission:

1. Normalize the submitted phone number using the exact same norm_phone()
   from scripts/common.py that Task 1's merge pipeline uses.
2. Look it up against people.primary_phone. If it matches an existing
   person (e.g. someone who was already in source1/2/3), link the new audio
   submission to that existing person_id instead of creating a duplicate.
3. If no match, create a new person row with matched_sources='audio_app' -
   this is a 4th "source" the people table now recognizes, alongside the
   original 3 CSVs.
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from common import norm_phone

BASE = Path(__file__).parent.parent
DB_PATH = BASE / "db" / "consultbae.db"
AUDIO_DIR = BASE / "uploads" / "audio"


def get_conn():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def find_or_create_person(conn, name: str, phone_raw: str) -> tuple[int, bool]:
    """Returns (person_id, was_newly_created)."""
    phone_norm = norm_phone(phone_raw)
    if phone_norm:
        existing = conn.execute(
            "SELECT person_id FROM people WHERE primary_phone = ?", (phone_norm,)
        ).fetchone()
        if existing:
            return existing["person_id"], False

    # No existing match (or phone couldn't be normalized) - create a new person.
    # New person_ids continue from whatever's already in the table so we never
    # collide with the 55 people Task 1 already created.
    max_id = conn.execute("SELECT COALESCE(MAX(person_id), 0) FROM people").fetchone()[0]
    new_id = max_id + 1
    conn.execute(
        "INSERT INTO people (person_id, canonical_name, primary_email, primary_phone, "
        "primary_city, matched_sources, match_method) VALUES (?, ?, NULL, ?, NULL, ?, ?)",
        (new_id, name.strip(), phone_norm, "audio_app", "single_source_only"),
    )
    conn.commit()
    return new_id, True


def save_submission(name: str, phone_raw: str, audio_bytes: bytes, file_ext: str, features: dict) -> int:
    """Persists the audio file to disk and inserts a row into audio_submissions,
    linked to the matched (or newly created) person. Returns the submission_id."""
    conn = get_conn()
    try:
        person_id, is_new = find_or_create_person(conn, name, phone_raw)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        safe_name = "".join(c for c in name if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_") or "anon"
        file_path = AUDIO_DIR / f"{timestamp}_{safe_name}.{file_ext}"
        file_path.write_bytes(audio_bytes)

        cur = conn.execute(
            "INSERT INTO audio_submissions "
            "(person_id, submitted_name, submitted_phone, file_path, duration_sec, "
            "sample_rate_hz, bitrate_kbps, loudness_db, noise_estimate, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                person_id, name.strip(), phone_raw.strip(), str(file_path),
                features["duration_sec"], features["sample_rate_hz"], features["bitrate_kbps"],
                features["loudness_db"], features["noise_estimate"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid, person_id, is_new
    finally:
        conn.close()


def list_submissions():
    """Returns all submissions joined with their matched person, newest first."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT s.submission_id, s.submitted_name, s.submitted_phone, s.file_path, "
            "s.duration_sec, s.sample_rate_hz, s.bitrate_kbps, s.loudness_db, "
            "s.noise_estimate, s.created_at, s.person_id, p.matched_sources "
            "FROM audio_submissions s LEFT JOIN people p ON s.person_id = p.person_id "
            "ORDER BY s.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def db_exists() -> bool:
    return DB_PATH.exists()
