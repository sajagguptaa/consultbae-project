"""
Task 2 — thin API bridge between n8n and db/consultbae.db.

Why this exists instead of pointing an n8n community SQLite node straight at
the .db file: n8n has NO built-in SQLite node (confirmed - there's an open
community forum thread asking why not, still unanswered as of the version
this was built against). The only options are unofficial community packages
that need separate installation on whoever's n8n instance runs this, which
is fragile for something a reviewer needs to just open and run. A plain
HTTP Request node (built into every n8n install, zero extra setup) hitting
a tiny local API is more portable and is also just... how this would
actually be built for a real client integration - n8n talks to backends
over HTTP in practice, not by reaching directly into a database file.

Endpoints:
  GET  /api/people/untagged   - people who have skills data but no
                                 skill_category yet, combining source1's
                                 `skills` and source2's `skill_tags` (a
                                 person can have either, or both)
  POST /api/people/<id>/tag   - writes the classified skill_category back

Run with: python3 app/db_api.py   (listens on http://localhost:8787)
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, jsonify, request

DB_PATH = Path(__file__).parent.parent / "db" / "consultbae.db"
app = Flask(__name__)

ALLOWED_CATEGORIES = {
    "automation-heavy", "web dev", "data", "voice/calling", "other",
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/api/people/untagged", methods=["GET"])
def untagged_people():
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT p.person_id, p.canonical_name,
                   a.skills AS applicant_skills,
                   g.skill_tags AS gig_skill_tags
            FROM people p
            LEFT JOIN applicant_profile a ON p.person_id = a.person_id
            LEFT JOIN gig_worker_profile g ON p.person_id = g.person_id
            WHERE p.skill_category IS NULL
              AND (a.skills IS NOT NULL OR g.skill_tags IS NOT NULL)
            ORDER BY p.person_id
            """
        ).fetchall()

        results = []
        for r in rows:
            skills_parts = [s for s in (r["applicant_skills"], r["gig_skill_tags"]) if s]
            # Dedupe case-insensitively across sources - a person appearing in both
            # source1 and source2 often has near-identical skill lists with different
            # casing (e.g. "n8n" vs "n8n", "SQL" vs "sql"), which would otherwise send
            # redundant, noisy text to the LLM. Found this while testing this endpoint
            # against real data - see stuck log.
            seen_lower = set()
            deduped = []
            for part in skills_parts:
                for item in [s.strip() for s in part.split(",") if s.strip()]:
                    if item.lower() not in seen_lower:
                        seen_lower.add(item.lower())
                        deduped.append(item)
            skills_text = ", ".join(deduped)
            results.append(dict(
                person_id=r["person_id"],
                canonical_name=r["canonical_name"],
                skills_text=skills_text,
            ))
        return jsonify(results)
    finally:
        conn.close()


@app.route("/api/people/<int:person_id>/tag", methods=["POST"])
def tag_person(person_id):
    body = request.get_json(silent=True) or {}
    skill_category = (body.get("skill_category") or "").strip().lower()

    if skill_category not in ALLOWED_CATEGORIES:
        return jsonify(
            error=f"'{skill_category}' is not one of the allowed categories: {sorted(ALLOWED_CATEGORIES)}"
        ), 400

    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE people SET skill_category = ?, skill_category_tagged_at = ? WHERE person_id = ?",
            (skill_category, datetime.now(timezone.utc).isoformat(), person_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify(error=f"No person with person_id {person_id}"), 404
        return jsonify(person_id=person_id, skill_category=skill_category)
    finally:
        conn.close()


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(status="ok", db_exists=DB_PATH.exists())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8787)
