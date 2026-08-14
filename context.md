# Context Handoff — ConsultBae Data Merge & Automation Assignment

This file is a handoff summary of everything done so far, written so a new developer (or a new AI assistant session) can pick this up without needing the original conversation. Read this top to bottom before touching code.

## The assignment (full spec, for reference)

Job application assignment with 5 tasks, 3 messy CSV files from 3 different systems ("ConsultBae" — recruitment gigs, CBNexus, internal automations), same people appear across files with no shared ID.

1. **Task 1 (core)** — Merge all 3 CSVs into one clean database. Same person across files = one record. No single ID field is common across all 3 files.
2. **Task 2 (core)** — One working n8n/Make/Zapier automation connected to the data. Pure-code solutions score zero here — must be no-code/low-code.
3. **Task 3 (core)** — Mini web app: enter name + phone, record audio in browser OR upload a file, submit → audio stored + record goes into the Task 1 database. Must auto-extract: duration, sample rate (kHz), bitrate, loudness (dB). Bonus: noise/quality estimate. Second view lists all submissions with a play button + properties.
4. **Task 4 (core)** — Written report of every data quality issue found and what was done about it. Must be specific.
5. **Task 5 (optional/stretch)** — One-pager, no code: what breaks if this audio app gets 5,000 gig workers in one weekend? Storage, uploads, failures, duplicates, cost.

**Submission requirements:** GitHub repo (commit history matters — they explicitly said they look at it), README with setup + data issues report, a "stuck log" (2-3 hardest sticking points, how you got unstuck, what you asked AI, what you rejected and why — **blank/generic stuck logs score zero**), and a ≤6min screen recording (voice required, face optional).

## Chronology followed so far (continue in this order)

We agreed on this build order and it's important to keep following it: **Task 1 → Task 4 → Task 3 → Task 2 → Task 5 → final polish**. Task 3 before Task 2 was deliberate — the n8n automation in Task 2 should hook into something real (the audio app / database) rather than being a standalone demo.

## Repo location & structure

Working locally at `consultbae-merge/` (this needs to be pushed to an actual GitHub repo — that hasn't happened yet, everything so far is local commits only).

```
consultbae-merge/
├── .gitignore
├── README.md                          # setup steps + Task 1 approach + full Task 4 report + stuck log
├── requirements.txt                   # currently just: pandas>=2.0  (NEEDS streamlit, pydub, numpy added — see Next Steps)
├── data/raw/                          # the 3 original CSVs, untouched
│   ├── source1_naukri_applicants.csv
│   ├── source2_gig_workers.csv
│   └── source3_cbnexus_contacts.csv
├── scripts/
│   ├── 01_profile.py                  # profiles raw files, prints issues found (read-only, no writes)
│   ├── 02_build_database.py           # THE core Task 1 pipeline — normalizes, matches, builds db/consultbae.db
│   └── common.py                      # NEW, uncommitted — shared normalize_phone/email/city helpers (see below)
└── db/
    ├── consultbae.db                  # generated SQLite output (untracked in git so far — decide whether to commit or gitignore)
    └── merged_people_full_export.csv  # generated flat export for manual review
```

## Git state — IMPORTANT, read before committing anything

Current commits (all local, not pushed anywhere yet):
```
cd8849a Add README with setup steps, Task 1 approach, data issues report (Task 4), and stuck log
f65c7cd Fix match_method mislabeling: track fallback merges explicitly instead of inferring from aggregate email/phone sets
4537869 Add profiling script + entity-resolution merge pipeline (union-find, tiered email/phone/name-city matching)
c54e3ef Add raw source CSVs (source1: naukri, source2: gig_workers, source3: cbnexus)
```

**Uncommitted / in-progress right now:**
- `scripts/common.py` — just created, NOT yet committed, and NOT yet wired up. It extracts `norm_phone`, `norm_email`, `norm_city`, `norm_name_key`, and `CITY_ALIASES` out of `02_build_database.py` so the same normalization logic can be reused by the Streamlit audio app (Task 3 needs to match submitted phone numbers against the same `people` table using identical rules — duplicating the logic would risk drift).
- `db/` folder — currently untracked. Decide and document whether to commit the generated `.db` file (convenient for reviewers to open directly) or gitignore it and rely on the build script (cleaner, but reviewer has to run the pipeline first). Either is defensible — just pick one and note the reasoning in the README, since "why" decisions are what this assignment is grading.

**Immediate next action:** finish the refactor — replace the inline `norm_email`/`norm_phone`/`norm_city`/`norm_name_key`/`CITY_ALIASES` definitions near the top of `02_build_database.py` with `from common import ...`, re-run the pipeline to confirm identical output (55 people, same match_method labels), then commit both files together as one logical change (e.g. "Extract shared normalization helpers into common.py for reuse in audio app").

## Task 1 — what was built and why (done, committed)

**The core problem:** no single ID field spans all 3 files. `source1` (naukri) has email + phone. `source2` (gig_workers) has ONLY email. `source3` (cbnexus) has ONLY phone. So a person in source2+source3 but not source1 has no directly shared field between those two rows.

**Solution: tiered Union-Find entity resolution** over all 102 raw rows from the 3 files:
- **Tier 1** (highest confidence): exact normalized email match → merge
- **Tier 2** (highest confidence): exact normalized phone match (last 10 digits, strips +91/0/91 prefixes) → merge
- **Tier 3** (fallback, lower confidence): name + canonical city match, but **only when not contradicted** by a phone/email that's present on both sides and disagrees. If a record is compatible with two DIFFERENT clusters that themselves conflict, it's left unmerged and flagged rather than guessed.

Result: **102 raw rows → 55 unique people**, full lineage preserved in a `source_lineage` table (every merge traces back to its original file + row number).

**A real bug was found and fixed during this build** (documented in the README stuck log, entry #2 — worth reading in full before touching the matching logic again): the first version of Tier 3 compared matches pairwise (row vs row) instead of against the whole cluster a row was about to join. Since `source2` has no phone field at all, a phone-less source2 record silently "bridged" two source3 records that had **directly conflicting phone numbers** (`...131` vs `...272`, both named "Arjun Mehta", both in Noida), merging 4 rows that should have produced 2 separate people. Fixed by comparing against the aggregate phone/email set of the entire cluster, and by adding a rule: if a record is compatible with 2+ clusters that conflict with each other, leave it unmerged (ambiguous) rather than pick one arbitrarily. **Verified fix**: Arjun Mehta now correctly resolves to `person_id 19` (source1+source3, phone `...131`) and `person_id 41` (source2+source3, phone `...272`) as two separate people.

**Schema built** (SQLite, `db/consultbae.db`):
- `people` (person_id, canonical_name, primary_email, primary_phone, primary_city, matched_sources, match_method)
- `source_lineage` (person_id → original file/row/raw values, full audit trail)
- `applicant_profile` (from source1: experience_years, ctc_annual_inr + ctc_unit_assumed, applied_date + ambiguity flag, skills)
- `gig_worker_profile` (from source2: rate_type/rate_value_inr kept separate rather than force-converted, status)
- `cbnexus_profile` (from source3: verified boolean, projects_completed)
- `audio_submissions` (**table already exists in the schema**, created empty, waiting for Task 3 to populate it — see below)

Run order: `python3 scripts/01_profile.py` (read-only, prints findings) then `python3 scripts/02_build_database.py` (rebuilds `db/consultbae.db` from scratch every run — idempotent by design, always drops and recreates the DB file).

## Task 4 — data issues report (done, committed, lives in README.md)

20 specific, evidence-backed issues catalogued with row numbers/values across: source1 (phone formats, city name variants, CTC unit ambiguity [Lakhs vs absolute rupees], 3 mixed date conventions in one column, 2 within-file duplicate people), source2 (blank row, a genuinely corrupted/column-shifted row, email casing, mixed rate units [/hr vs k/month], status casing + stray 3rd value), source3 (an embedded duplicate header row mid-file, phone format variants, Verified column casing), and cross-source issues (the no-common-ID problem, the Arjun Mehta ambiguous-duplicate case, an orphaned "Deepak Nair" record only in source2).

Full detail is in `README.md` under "Data Issues Report (Task 4)" — don't summarize from memory, read that section directly, it's specific and the assignment explicitly grades specificity.

## Stuck Log (done, committed, lives in README.md)

3 honest entries already written: (1) designing a matching strategy with no common ID, (2) the transitive-merge bug described above — including that this was caught by manually checking real output rather than trusting a summary count, (3) a design-philosophy point about flagging ambiguity rather than silently guessing (applies to both the date-parsing ambiguity and the Arjun Mehta case). **Do not overwrite these** — they're written honestly including a real mistake, which is exactly what the assignment is grading for ("blank or generic stuck logs score zero"). Any new stuck points from Task 2/3/5 should be *added* to this section, not replace it.

## Task 3 — audio app (IN PROGRESS, this is where to resume)

**Decisions already locked in** (confirmed with the person building this, don't re-ask):
- **Stack: Streamlit** (chosen for speed over Flask)
- **Audio input: BOTH** browser recording and file upload (not just one)

**Plan discussed but not yet built:**
- Use Streamlit's native `st.audio_input()` widget for browser mic recording (available in modern Streamlit — always returns WAV bytes, no custom JS component needed) and `st.file_uploader()` for uploads (accept wav/mp3/m4a/ogg/flac).
- Environment check already done: **ffmpeg is available** at `/usr/bin/ffmpeg` in the dev sandbox, and Python is 3.12.3 — so `pydub` (which shells out to ffmpeg) will handle any uploaded format cleanly, not just WAV. If deploying to Streamlit Cloud, remember to add a `packages.txt` file containing `ffmpeg` (Streamlit Cloud needs that to install system-level ffmpeg — pip alone won't do it).
- **Audio feature extraction plan** (not yet coded):
  - `duration_sec`, `sample_rate_hz`, `channels` — straight from `pydub.AudioSegment` (`len(seg)/1000`, `seg.frame_rate`)
  - `loudness_db` — from `seg.dBFS` (pydub's built-in loudness-relative-to-full-scale measure). **Watch out**: `dBFS` returns `-inf` for pure silence — needs explicit handling (e.g. `math.isinf()` check) rather than storing `-inf` directly in SQLite.
  - `bitrate_kbps` — deliberately computed as **effective bitrate** = `(file_size_bytes * 8) / duration_sec / 1000`, NOT the encoder's nominal bitrate metadata. Reasoning already decided: this works uniformly across compressed and uncompressed formats without needing format-specific metadata parsing (e.g. via `mutagen`), and is defensible as "how many bits per second this file actually occupies." Worth stating this reasoning explicitly in the README when this section gets written, since it's a judgment call an interviewer could reasonably question.
  - **Bonus noise/quality estimate** — planned approach: downmix to mono via `seg.get_array_of_samples()` → numpy array, compute short-time RMS envelope in ~50ms frames, take the 10th percentile as an approximate noise floor and 90th percentile as approximate signal level, compute `20*log10(signal/noise)` as an approximate SNR in dB, then bucket into "Clean" (>30dB) / "Some background noise" (15-30dB) / "Noisy" (<15dB). This is a deliberately simple, explainable heuristic — not a proper perceptual loudness/noise model — and that tradeoff (simplicity/explainability vs. accuracy) is worth being able to defend in the interview.
- **Database integration** (the part that makes this "Task 3" and not just a standalone toy app): on submit, normalize the entered phone number using the **same** `norm_phone()` from `scripts/common.py` (hence the refactor happening right now), look up whether it matches an existing `people.primary_phone`. If yes, link the new `audio_submissions` row to that existing `person_id`. If no, insert a new `people` row with `matched_sources='audio_app'`. This reuses Task 1's matching logic instead of treating the audio app as a disconnected feature.
- **Second view** ("all submissions" list): query `audio_submissions` joined to `people`, show name/phone/duration/sample rate/bitrate/loudness/noise estimate per row, with `st.audio()` as the play button (it accepts raw bytes or a file path directly).

**Not yet done at all:**
- No `app/` folder or `streamlit_app.py` file exists yet.
- `requirements.txt` still only has `pandas` — needs `streamlit`, `pydub`, `numpy` added.
- No `packages.txt` (needed for ffmpeg on Streamlit Cloud deployment) yet.
- Audio storage location not yet decided in code (plan: save files under `uploads/audio/`, which is already gitignored — path referenced in `audio_submissions.file_path`).
- No testing done yet — recommend testing the extraction function against a synthetically generated WAV (e.g. a sine wave via numpy) before relying on real mic input, since mic recording can't be tested headlessly in a sandboxed dev environment.

## Task 2 — n8n automation (NOT STARTED)

Plan discussed: lean toward the **LLM auto-tagging flow** (n8n → reads a person's `skills`/`skill_tags` field from the database → Claude API call to classify into a skill category like "automation-heavy" / "web dev" / "data" → writes the tag back to the database) rather than the duplicate-alert flow, since it better showcases real automation-stack experience. Not yet built. Should be built **after** Task 3 so it has a real audio-app-fed database to connect to. Remember: **pure-code solutions score zero here** — must actually be built in n8n (or Make/Zapier) and the flow JSON exported into the repo, with the run shown in the video.

## Task 5 — scaling stretch doc (NOT STARTED)

One-pager, no code. Needs to cover: what breaks first at 5,000 concurrent gig worker submissions over a weekend (local disk storage won't survive a redeploy — needs object storage like S3; SQLite write contention under concurrent load — would need to swap to Postgres; synchronous audio processing blocking uploads — needs a queue; duplicate submission handling; idempotency/retries; rough cost estimate). Should be written last, after Task 3 is actually built, so it can reference real bottlenecks in the actual implementation rather than being generic.

## Final steps not yet done (after all 5 tasks)

- Push the local repo to an actual GitHub repository (hasn't happened — everything is local commits so far).
- Deploy the Streamlit app somewhere free (Render/Streamlit Cloud) OR plan to demo it running locally in the screen recording.
- Record the ≤6min Loom/screen recording: run the Task 1 pipeline, show the audio app end-to-end, walk through the 2-3 hardest decisions (the Arjun Mehta merge bug is the strongest one to walk through on camera — it's specific and shows real debugging, not just "I used AI to generate code").
