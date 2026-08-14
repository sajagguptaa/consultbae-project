# ConsultBae — Multi-Source Data Merge & Automation Assignment

## What this repo contains (so far)

- `data/raw/` — the 3 original source CSVs, untouched
- `scripts/01_profile.py` — profiles all 3 files and prints every data quality issue found, before any cleaning happens
- `scripts/02_build_database.py` — normalizes, resolves duplicate people across sources, and builds `db/consultbae.db` (SQLite)
- `scripts/common.py` — shared normalization helpers (phone/email/city), used by both the merge pipeline and the audio app so matching logic never drifts out of sync between them
- `app/streamlit_app.py` — Task 3 audio collection app (submit view + all-submissions view)
- `app/audio_utils.py` — audio feature extraction (duration, sample rate, bitrate, loudness, noise estimate)
- `app/db_utils.py` — links audio submissions to the Task 1 database via phone matching
- `app/db_api.py` — Flask API bridge for Task 2 (n8n has no built-in SQLite node, so this exposes the DB over HTTP)
- `scripts/03_add_skill_category_column.py` — idempotent migration adding the column Task 2 writes into
- `n8n/skill_tagging_workflow.json` — the Task 2 automation, verified by actually running it end-to-end (not just hand-authored)
- `tests/test_audio_utils.py` — regression tests for the audio extraction logic
- `db/consultbae.db` — the merged database (generated; safe to delete and re-run, the script is idempotent)
- `requirements.txt`, `packages.txt` — Python deps + system deps (ffmpeg, for Streamlit Cloud deployment)

All 5 tasks are now complete — see README sections below for each.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python3 scripts/01_profile.py      # prints the raw data quality findings
python3 scripts/02_build_database.py   # builds db/consultbae.db
python3 scripts/03_add_skill_category_column.py   # adds the column Task 2 writes into

# Task 3 - audio app (needs db/consultbae.db built first)
streamlit run app/streamlit_app.py

# Task 2 - n8n automation (needs db/consultbae.db built first)
python3 app/db_api.py              # starts the API bridge on localhost:8787, leave running
n8n import:workflow --input=n8n/skill_tagging_workflow.json
n8n start                          # then open the n8n editor UI and see setup steps below
```

**Task 2 one-time setup after importing:** open the "Classify Skill Category (Claude)" node in the n8n editor → Authentication → Header Auth → create a new credential named `x-api-key` with your real Anthropic API key as the value → save. Then run the workflow from the editor (click "Execute workflow" on the Manual Trigger). `app/db_api.py` must be running in a separate terminal the whole time — n8n calls it over HTTP.

No API keys or external services needed for Tasks 1/3. Task 2 needs your own Anthropic API key (added as an n8n credential, never committed to this repo).

The audio app needs `ffmpeg` installed on the system (already present on most Linux/Mac setups — check with `ffmpeg -version`; on Streamlit Cloud, `packages.txt` in this repo handles it automatically).

**Known gotcha on Python 3.13+:** Python 3.13 removed the stdlib `audioop` module, which `pydub` depends on internally. If you see `ModuleNotFoundError: No module named 'audioop'` (or `'pyaudioop'`), it means you're on 3.13+ — run `pip install audioop-lts` to fix it (this is already in `requirements.txt` as a conditional dependency for Python ≥3.13, so a fresh `pip install -r requirements.txt` should handle it automatically, but is worth knowing if it doesn't for some reason — e.g. a stale/cached venv from before this was added).

To run the audio extraction tests: `python3 -m pytest tests/test_audio_utils.py -v`

## Task 1 — Merge approach (short version)

None of the 3 files share a single ID field:
- `source1` (naukri) has email **and** phone
- `source2` (gig_workers) has **only** email
- `source3` (cbnexus) has **only** phone

So a person appearing only in source2 and source3 has *no directly shared field* between those two records. I resolved identity using a tiered, confidence-ranked matching strategy (Union-Find over all 102 raw rows):

1. **Exact email match** (normalized: lowercased, trimmed) — highest confidence
2. **Exact phone match** (normalized: strip all non-digits, compare last 10 digits) — highest confidence
3. **Name + city fallback**, used only when the two records being compared don't already have a phone or email that actively *disagrees*. If a person is name+city-compatible with two *different* clusters that themselves conflict with each other, the pipeline does not guess — it leaves them unmerged and logs it for manual review.

Result: 102 raw rows → **55 unique people**, with full row-level lineage kept in `source_lineage` so every merge decision is auditable back to the original file/row.

## Data Issues Report (Task 4)

### Source 1 — `source1_naukri_applicants.csv`

| # | Issue | Evidence | What I did |
|---|-------|----------|------------|
| 1 | **Phone number format inconsistency** — three formats mixed in one column: `+919000000254`, `9000000237`, `09000000287` | 30 rows plain 10-digit, 12 rows with `+91` or leading `0` | Normalized to last 10 digits for all matching and storage; kept the raw value in `source_lineage` |
| 2 | **City name inconsistency** — casing, trailing whitespace, and genuine naming variants | `GURGAON`, `Gurugram`, `gurugram ` (trailing space) all refer to the same city; same for `Bangalore`/`Bengaluru`, `NOIDA`/`Noida`/`Noida `, `Delhi`/`New Delhi`/`new delhi` | Built a canonical city alias map (Gurgaon→Gurugram, Bangalore→Bengaluru, New Delhi→Delhi, official renamings). `Delhi NCR` was **not** folded into `Delhi` — it's a region, not a specific city (e.g. Amit Reddy, row 36), so collapsing it would have been a bigger assumption than the data supports. Flagged, kept distinct. |
| 3 | **Current CTC has two different units mixed in one column** — some values are absolute annual rupees (`417964`), others are figures in Lakhs (`4.2`) | 21 of 42 rows are <100 (clearly Lakhs — no one's annual salary is ₹4.2), 21 are ≥100 (absolute rupees) | If value < 100, multiplied by 100,000 to get `ctc_annual_inr`; stored `ctc_unit_assumed` (`lakhs`/`absolute`) alongside the raw value so the assumption is visible and reversible, not silently baked in |
| 4 | **Applied Date mixes 3 different date conventions in one column** — ISO (`2026-08-08`), Indian dash format (`24-07-2026` = DD-MM-YYYY), US slash format (`07/13/2026` = MM/DD/YYYY — confirmed because day values like 13/19/21 can't be months), and named-month (`7 Jul 2026`) | e.g. rows with `07/13/2026` vs `24-07-2026` in the same column | Parsed each format based on its separator pattern into `applied_date` (ISO). For slash-dates where **both** segments are ≤12 (e.g. `07/03/2026` — could be July 3 or March 7), there's no way to be certain from the data alone. I applied the MM/DD convention for consistency with the unambiguous slash-dates in the same column, but flagged these rows with `applied_date_ambiguous = 1` rather than presenting them as certain. **4 rows** are flagged this way. |
| 5 | **Duplicate person within the same file, different name spelling** — "Rohit Verma" (row 31) and "R. Verma" (row 25) share the exact same email and phone | `rohit.verma13@mailtest.example.org`, `9000000294`, both Bangalore | Collapsed to one `applicant_profile` row (kept the fuller name), other row logged in `source_lineage` as a detected duplicate, not deleted |
| 6 | **Duplicate person, alternate email address** — two "Nikhil Chopra" rows (27 and 37) with the *same phone* but *different email* (`alt.nikhil.chopra70@...` vs `nikhil.chopra70@...`) | Phone `9000000103` identical in both | Matched via phone (Tier 2), collapsed to one profile. This is a good example of why phone was needed as a second matching key — email alone would have missed this pair entirely |

### Source 2 — `source2_gig_workers.csv`

| # | Issue | Evidence | What I did |
|---|-------|----------|------------|
| 7 | **A fully blank row** | Row 12 in the raw file, all 6 fields empty | Dropped during cleaning; not counted as a person |
| 8 | **A structurally corrupted / column-shifted row** — the skill tags from a previous row leaked into the `email_id` field, and every other field shifted one column left | Row 20: `email_id` = `"react, javascript, mysql"` (that's actually skill data), `status` = `Pune` (that's actually a city) | Detected via a validity check (`email_id` must contain `@`) rather than trusting the column position. Dropped this row from the clean set — it's a corrupted duplicate of the Isha Chopra record already present correctly on row 7, so no data was actually lost |
| 9 | **Email casing inconsistency** — some rows fully uppercase (`ISHA.CHOPRA95@MAILTEST.EXAMPLE.ORG`), most lowercase | 8 of 30 clean rows uppercase | Lowercased before every match comparison and before storage as `primary_email` |
| 10 | **Rate column mixes two incompatible units** — hourly (`1415/hr`) and monthly (`72k/month`) in the same field | 16 hourly, 14 monthly | Did **not** force-convert between them — converting hourly→monthly requires an assumed working-hours figure I'd be fabricating. Instead stored `rate_type` and `rate_value_inr` as separate typed fields so downstream consumers can apply their own assumption explicitly rather than inheriting mine silently |
| 11 | **Status column casing inconsistency, plus a 3rd status value** | `Active`, `active`, `ACTIVE`, `Inactive`, and `paused` (lowercase, never capitalized in the raw data) | Canonicalized to `Active` / `Inactive` / `Paused` |
| 12 | **No phone field at all** — structurally limits how this source can be matched | N/A — this is a schema-level issue, not a row-level one | Documented as a design constraint driving the tiered matching strategy (see Task 1 approach above) |

### Source 3 — `source3_cbnexus_contacts.csv`

| # | Issue | Evidence | What I did |
|---|-------|----------|------------|
| 13 | **An entire second header row embedded mid-file** — looks like two exports were concatenated without stripping the second file's header | Line 16: `Name,Phone Number,City,Verified,Projects Completed` repeated verbatim | Detected by comparing every row against the header string and dropping exact matches after row 1 |
| 14 | **Phone number format inconsistency** — 3 different formats | `9000000268` (plain), `919000000231` (91-prefixed, no +), `+91-9000000131` (hyphenated) | Normalized to last 10 digits, same as source1 |
| 15 | **Verified column inconsistency** | `Y`, `yes`, `Yes`, `N`, `No` mixed | Canonicalized to boolean (1/0) |
| 16 | **Same city inconsistency as source1** (casing, trailing space, Gurgaon/GURGAON) | — | Same canonical city map applied |
| 17 | **Two "Arjun Mehta" records, same city (Noida), different phone numbers** (`+91-9000000131` on row 5 vs `9000000272` on row 28) | Genuinely ambiguous — could be 2 different real people who happen to share a name and city, or a data entry error | This is the trickiest case in the whole dataset. See the matching strategy above — **not** merged, because the phone numbers actively conflict. Ended up as 2 separate `person_id`s (19 and 41). Flagged explicitly in the match log for a human to review if this were a real production dataset — I would not want an automated pipeline silently guessing on this. |
| 18 | **No email field at all** — same structural limitation as source2's missing phone | N/A | Same as issue #12 — informed the tiered matching design |

### Cross-source issues

| # | Issue | Evidence | What I did |
|---|-------|----------|------------|
| 19 | **No single ID field common to all 3 files** | email links source1↔source2, phone links source1↔source3, but source2↔source3-only people (e.g. Manish Bhatia, Divya Chopra, Karan Chopra, Vikram Mehta) have *no* directly shared field | Name + city fallback matching, with the conflict-safety rule described above |
| 20 | **A person who exists in only 1 of the 3 sources but shares a name with someone else in the dataset** — "Deepak Nair" in source2 (`deepak.nair57@example.in`, New Delhi) vs the "Deepak Nair" who appears in all 3 sources (Bengaluru, phone `...296`) | Different cities, no phone on the source2-only record to cross-check | Correctly kept as 2 separate people — the city mismatch alone rules out a merge under the name+city fallback rule. This person (`person_id 54`) has no phone on file, so if this were real, it'd be worth flagging to the CBNexus/gig team as an "unverified — could not be cross-referenced" record |

## Task 3 — audio app approach

**Stack:** Streamlit (chosen over Flask for build speed), with `pydub` (backed by `ffmpeg`) for audio decoding and `numpy` for the loudness/noise math.

**Both input methods, as required:** `st.audio_input()` for in-browser mic recording (always produces WAV) and `st.file_uploader()` for uploading existing files (wav/mp3/m4a/ogg/flac — `pydub`+`ffmpeg` decodes all of them uniformly, so format isn't a special case in the extraction code).

**What gets auto-extracted per submission:**
- `duration_sec`, `sample_rate_hz`/`sample_rate_khz`, `channels` — read directly from the decoded audio via `pydub`
- `loudness_db` — reported as dBFS (decibels relative to full scale) via `pydub`'s built-in `.dBFS`. Silence produces `-inf`, which is explicitly detected and stored as `NULL` rather than a non-finite float (SQLite/JSON can't represent `-inf` cleanly)
- `bitrate_kbps` — deliberately computed as **effective bitrate** = `(file size in bits) / duration`, not the format's nominal encoded bitrate metadata. This was a conscious tradeoff: parsing true encoder bitrate would need format-specific metadata handling (e.g. a separate library like `mutagen`) and would report inconsistently across formats, whereas effective bitrate is uniform regardless of input format. Validated this is a reasonable proxy, not just theoretically defensible — an mp3 encoded at 128kbps came back as 132.6kbps through this method, close enough to trust
- **Bonus — noise/quality estimate:** short-time RMS energy in ~50ms frames, with the 10th percentile treated as an approximate noise floor and the 90th percentile as an approximate signal level; their ratio in dB is reported as an approximate SNR, bucketed into Clean / Some background noise / Noisy. This is a deliberately simple heuristic, not a real perceptual noise model — see stuck log entry #4 for a real bug this caught during testing

**Database integration (what makes this "Task 3" and not just a standalone toy):** on submit, the entered phone number is normalized with the *same* `norm_phone()` from `scripts/common.py` that Task 1's merge pipeline uses, then looked up against `people.primary_phone`. A match links the submission to that existing `person_id`; no match creates a new person with `matched_sources='audio_app'` — a 4th source the `people` table now recognizes alongside the original 3 CSVs. Verified both paths work correctly against the real database (existing person: `Tanvi Gupta` → matched to `person_id 1`; new person: `Rakesh Kumar` → created as `person_id 56`).

**Testing approach:** rather than only testing by clicking through the browser UI, the audio extraction logic (`app/audio_utils.py`) has its own test suite (`tests/test_audio_utils.py`) using synthetically generated WAV signals — a speech-shaped signal (tone bursts + silence gaps, to actually resemble real speech) at three noise levels, plus silence and format-conversion edge cases. This is what caught the bug described below before it ever reached a real recording.

## Task 2 — n8n automation approach

**What it does:** an n8n workflow (`n8n/skill_tagging_workflow.json`) that reads every person in the database who has skills data but no `skill_category` yet, sends their skills to Claude for classification into one of `automation-heavy` / `web dev` / `data` / `voice/calling` / `other`, and writes the result back — end to end, no manual step in between.

**Why an API bridge instead of a direct DB connection:** confirmed via research before building anything — n8n has **no built-in SQLite node** (there's an open community forum thread asking why not, still unanswered). The only options are unofficial community node packages that would need separate installation on whoever's n8n instance runs this, which is fragile for a reviewer who just wants to open this and have it work. Built a tiny Flask API (`app/db_api.py`) instead, and n8n talks to it with its core HTTP Request node — zero extra n8n setup required, and honestly this is also just how this would actually be built for a real client integration (no-code tools talk to backends over HTTP in practice, not by reaching into a database file directly).

**Workflow structure:** Manual Trigger → `GET /api/people/untagged` → (n8n auto-splits the JSON array response into one item per person — verified empirically, no separate Split Out node needed) → `POST` to Claude for classification → Code node parses/validates the response → `POST /api/people/{id}/tag` writes it back.

**Verification approach:** rather than hand-author the JSON and assume it's correct, I actually installed n8n locally, imported this exact workflow via its CLI, and ran it end-to-end against the real merged database — first with a local mock standing in for the Claude API call (to validate the wiring without spending real API credits), confirming all 55 people got correctly tagged with a sensible category distribution before ever touching the real Anthropic endpoint. This caught a real, non-obvious bug — see stuck log entry #6.

**One-time setup required** (can't be exported in the JSON, and shouldn't be — it's a secret): after importing, the "Classify Skill Category (Claude)" node needs a Header Auth credential named `x-api-key` with your own Anthropic API key as the value. Exact steps are in the Setup section above.

## Task 5 — Scaling stretch: what happens at 5,000 gig workers in a weekend

*One page, no code — what breaks and what I'd change before a real launch, grounded in the actual implementation above rather than generic scaling advice.*

### What breaks first

**1. Local disk storage for audio files — breaks almost immediately on most free hosts.** `uploads/audio/` writes to local disk. Render's and Streamlit Cloud's free tiers use ephemeral filesystems — any redeploy, restart, or scale-to-zero event wipes every submitted recording. At 5,000 submissions this isn't a capacity problem, it's a certainty problem: the files *will* disappear, not might.

**2. SQLite write contention.** SQLite allows one writer at a time; concurrent writers queue and, past a short timeout, fail outright. Sustained submissions from a genuinely large weekend spike (launch announcements tend to cluster traffic in bursts, not spread evenly across 48 hours) will produce `database is locked` errors under real concurrent load — this isn't hypothetical, it's a documented SQLite behavior under concurrent writers.

**3. The Flask dev server can't handle concurrent requests properly.** `app/db_api.py` runs on Flask's built-in development server, which prints its own warning about this on startup ("do not use in production") — it's essentially single-threaded and will queue or drop requests under real concurrent load from n8n and the audio app hitting it at once.

**4. Synchronous audio processing blocks the request.** `analyze_audio()` runs inline during the Streamlit submit action — decoding via ffmpeg and computing the noise estimate happens before the user sees a response. Fine for a demo with one user; at scale, submissions queue behind each other and the app feels like it's hanging, especially for longer recordings.

**5. A real race condition in person-matching.** `app/db_utils.py`'s `find_or_create_person()` is a check-then-insert: SELECT to look for an existing phone match, then INSERT if none found. Nothing stops two near-simultaneous submissions from the same new phone number (a double-tap, a retry after a slow response, or a genuine coincidence at 5,000 people) from both passing the "not found" check and creating two separate person records for what should be one person — undoing exactly the kind of duplicate-person problem Task 1 was built to solve in the first place.

### What I'd change before launch

- **Storage:** move audio files to S3 (or GCS/R2) immediately — not as a later optimization, as a prerequisite. Store the object key in `audio_submissions.file_path` instead of a local path.
- **Database:** migrate from SQLite to Postgres. This directly fixes the write-contention problem (real concurrent writers, not single-writer locking) and lets the phone-matching race condition be closed properly with a `UNIQUE` constraint on `people.primary_phone` plus an `ON CONFLICT` upsert, instead of the current check-then-insert pattern.
- **Uploads/failures:** decouple the upload from the processing. Accept the file and return success immediately, push the actual `analyze_audio()` work onto a background queue (Celery+Redis, or even a simple SQS-backed worker), and update the submission record asynchronously once extraction finishes. This also gives a natural place to retry failed extractions instead of the current single-attempt `st.error()` and a dead end.
- **Duplicates:** decide the actual business rule (is a second submission from the same phone a correction, a retry, or spam?) and enforce it explicitly — right now there's no submission-level dedup at all, only person-level matching. A simple idempotency key (client-generated, sent with the submission) would catch accidental double-submits from network retries, which is the most likely real-world case.
- **Cost:** rough shape of it — S3 storage for 5,000 short recordings (~1-2MB each) is a few dollars a month, genuinely not the concern. The real cost risk is egress/bandwidth if the "All Submissions" play-button view gets used heavily (every playback re-downloads the file), and compute cost if audio processing moves to always-on background workers rather than scaling to zero between bursts.
- **One thing I'd explicitly *not* over-engineer for a weekend launch:** full autoscaling infrastructure. 5,000 submissions over 48 hours is a real but modest load (roughly 100/hour on average, more concentrated around a launch announcement) — Postgres + S3 + a single background worker process handles this comfortably. The failure modes above are about correctness and durability (don't lose data, don't create duplicate people, don't silently drop writes), not about needing a large distributed system.

## Stuck Log

**These are written honestly, including where the first version of the code was wrong** — the assignment specifically says generic stuck logs score zero, so here's exactly what happened, including the part where the AI-assisted first pass had a real bug.

### 1. Designing a matching strategy when no file shares a common ID with the others

The obvious first instinct is "match on email, or phone, whichever exists" — but that doesn't handle the case where two records need to be linked and neither has the *other* record's identifying field (e.g. a source2 email-only record and a source3 phone-only record for the same person, with no source1 record to bridge them). I asked Claude to think through this with me, and we landed on the concept of **entity resolution** with **tiered/blocking match confidence** — treat exact-ID matches as high-confidence, and use name+location as a lower-confidence fallback only when nothing contradicts it. I didn't just accept "fuzzy match everything by name" as a suggestion, because with 40-50 people sharing a small pool of common Indian first/last names (multiple "Arjun", "Deepak", "Chopra", "Mehta"), pure name-similarity matching would have produced false merges. Requiring city agreement too, and blocking on any conflicting phone/email, was the part I pushed back on and asked to be made stricter.

### 2. A real bug: the matching logic silently merged two people who should have stayed separate

After the first version of the merge script ran, I asked to see the actual output for the "Arjun Mehta" case specifically (rather than just trusting a "55 people" summary count), and found all 4 raw Arjun Mehta rows — including two source3 rows with **conflicting phone numbers** (`...131` and `...272`) — had collapsed into a single person. That should never happen; conflicting phone numbers are exactly the case the matching logic was supposed to protect against.

The root cause: the first version only compared *pairs* of raw rows when deciding whether to merge, not the *whole cluster* a row was about to join. Source2's record (no phone at all) didn't conflict with *either* of the two conflicting source3 records when checked individually, so it acted as a silent bridge connecting two records that directly contradicted each other. I rejected the idea of just special-casing "ignore source2 in fallback matching" (Claude raised this as a quicker fix) because that would break the exact case this fallback tier exists for (source2-to-source3-only people like Manish Bhatia). Instead the fix was to compare against the aggregate phone/email set of the entire cluster a row is about to join, and — if a row is genuinely compatible with two clusters that conflict with each other — leave it unmerged and flag it rather than guess. Re-ran and manually re-verified the Arjun Mehta case specifically (not just the summary counts) before moving on.

### 3. Deciding when the pipeline should guess vs. flag for a human

Several places in this dataset don't have a definitively "correct" answer from the data alone — the ambiguous `07/03/2026`-style dates, and the Arjun Mehta identity question above. My first instinct was to just pick the more common interpretation and move on, since guessing gets a "cleaner-looking" result. I changed my mind on this after thinking about what actually happens downstream: a merge tool that's *wrong 5% of the time but never says so* is more dangerous in a real system than one that's occasionally uncertain but honest about it, because someone will build automation on top of "clean" data that silently has errors baked in. So the rule I settled on: anywhere the data is genuinely ambiguous, store both the raw value and an explicit ambiguity flag (`applied_date_ambiguous`, the unmerged Arjun Mehta records) instead of collapsing to a single confident-looking answer.

### 4. The noise-estimate heuristic looked correct on paper but failed my first test case

For the bonus noise/quality estimate in Task 3, my first version computed the ratio between the loudest and quietest 50ms frames of an audio clip as an approximate SNR. It looked reasonable in the code and I nearly moved on without testing it against anything. Instead I generated a synthetic clean sine tone and a noisy version of the same tone to check the numbers actually made sense — and got back an almost identical ~0dB "noisy" reading for *both*, including the clean one.

The bug wasn't in the noise math — it was in my test signal. A continuous, unvarying tone has essentially the same energy in every single frame, so its 10th and 90th percentile frame-energy are nearly identical regardless of how much noise is layered on top; there's no quiet moment for the heuristic to measure a "floor" from. Real speech isn't like that — it has pauses between words, which is exactly what the heuristic needs to find a noise floor. I rejected the instinct to just tweak the percentile thresholds to "fix" the numbers on the bad test case, since that would have been curve-fitting to a test signal that wasn't representative of the actual use case (people submitting spoken voice memos) in the first place. Instead I rebuilt the test signal to be speech-shaped (tone bursts separated by real silence gaps) and re-ran — clean vs. moderate noise vs. heavy noise then came back as 60dB / 9.6dB / 2.0dB, correctly ordered. Also added an explicit near-silence guard afterward, since a genuinely silent clip was separately producing a nonsense "noisy, 0dB" reading for the same underlying reason (dividing two near-zero numbers isn't a real measurement). Both fixes are now covered by actual regression tests in `tests/test_audio_utils.py`, not just a one-off manual check.

### 5. `pydub` broke outright on my actual machine — Python 3.13 removed a module it depends on

I'd flagged this exact risk in the README and context.md while still developing in the sandbox (Python 3.12, where `pydub`'s `audioop` dependency showed a deprecation warning but still worked) — but flagging a risk and having it actually happen are different things. The moment I ran the app on my own laptop (Python 3.13, Windows), it broke on startup: `ModuleNotFoundError: No module named 'audioop'`, and pydub's own fallback path then failed too with `No module named 'pyaudioop'`.

I didn't guess at a fix (pinning an older pydub version was my first instinct, but that risks losing compatibility/bugfixes for no real reason). I asked Claude to look into it, and it searched rather than answering from memory — worth calling out, since a wrong guess here would've cost real debugging time. It turned up that Python 3.13 removed the `audioop` stdlib module entirely (PEP 594), that pydub's own fallback to `pyaudioop` doesn't actually work either (no such package is published under that exact name), and that the real fix is a separate backport package called `audioop-lts`, maintained specifically to plug this gap and installable as a drop-in replacement (it registers itself importable as `audioop`, so pydub's original `import audioop` line just works once it's installed). One command — `pip install audioop-lts` — fixed it immediately.

Rather than leave this as a one-off local fix, added it to `requirements.txt` as `audioop-lts>=0.2; python_version >= "3.13"` — a conditional dependency using pip's environment markers, so it only installs where it's actually needed (3.13+) and doesn't affect the 3.12 dev environment. Also documented it explicitly as a known gotcha in the README setup steps, since the next person hitting this exact traceback shouldn't have to go through the same search — the fix should just already be sitting in the requirements file by the time they run `pip install -r requirements.txt`.

### 6. An n8n workflow reported "success" while silently only processing 1 of 55 people

For Task 2, I didn't want to hand-author the workflow JSON and just hope the node types and parameters were right — so I actually installed n8n locally and ran the real workflow against the real database (with a local mock standing in for the Claude API call, to test the wiring without spending real API credits). The CLI reported `"status": "success", "finished": true` with no errors. I could have stopped there and called it verified.

Instead I checked the actual database afterward — the thing the workflow was supposed to change — and found only **1 of 55 people** had been tagged, not all of them. "Success" and "correct" turned out to be different things: the workflow ran without throwing an error, but it wasn't doing what it was supposed to do.

The cause: n8n's Code node has two execution modes — "Run Once for All Items" (the default) and "Run Once for Each Item." I'd written the code assuming per-item context (`$input.item`, returning a single object), which is only correct in the second mode. In the default mode, returning a single object instead of an array of objects silently discards every item except the first — no warning, no error, nothing in the execution log to suggest data was lost. I rejected the idea of just wrapping my existing code in a loop inside the "all items" mode as a patch, since that would leave the underlying mode mismatch in place for anyone editing this workflow later without knowing the gotcha existed. Instead set the node's mode explicitly to `runOnceForEachItem`, matching what the code actually assumes, re-ran the same test, and confirmed via the database (not the CLI's "success" message) that all 55 people were now tagged with a sensible spread across categories.

The broader lesson I took from this, worth stating plainly: **a tool reporting success only tells you it didn't crash — it doesn't tell you it did the right thing.** The only way to actually know is to check the state that was supposed to change. This is the second time in this project a "looks correct" first pass turned out to be silently wrong (the first was the merge pipeline's transitive-merge bug) — different bugs, same root cause: trusting an execution summary instead of the actual output.
