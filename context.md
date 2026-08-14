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

## Git & AI workflow — read this before making any more commits

The commits so far were made inside an AI-assisted sandbox session, all within a short window — the messages are accurate and each represents one real decision, but the timestamps don't reflect genuine day-by-day progress. **Do not try to fix this by rewriting history** (`git commit --amend --date=...`, `filter-branch`, rebasing with fake `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`, etc.) — that's fabricating evidence on a job application, not a workflow improvement. The existing history is fine to keep as-is; if it comes up, "built with AI assistance, see the stuck log for the actual decision points" is a normal thing to say, and the assignment itself asks what you asked AI, so this is expected here, not something to hide.

Going forward — whether you're driving an AI coding assistant (Claude Code, Cursor, etc.) yourself or handing this file to one to work from — follow these rules so the *future* history actually earns its keep:

1. **Commit per logical unit of work, not one batch at the end of a session.** Look at the 5 commits already in this repo as the pattern to match: raw data as its own commit, the matching pipeline as its own commit, the bug fix as a *separate* commit from the pipeline it fixes (don't squash a fix into the commit that introduced the bug — the fix being visible as its own step is exactly what makes a stuck-log story checkable), the report separately again. If an AI tool defaults to dumping everything into one commit at the end, explicitly instruct it not to.
2. **Commit messages explain the "why," not just the "what."** `git log --oneline` should read as a decision trail a reviewer can follow without opening every diff. "Fix match_method mislabeling: track fallback merges explicitly instead of inferring from aggregate email/phone sets" is the bar — not "fix bug" or "update script."
3. **Let timestamps happen naturally.** No trick needed here — if work on Task 3 happens today and Task 2 happens two days from now, the commits will land on different days on their own. The only failure mode to avoid is doing everything in one sitting and then wishing it looked spread out.
4. **Push to GitHub regularly, not just once at the end.** Local AI coding tools commit to your real local `.git`, so the "sandbox disappears" problem from earlier doesn't apply once this is running on an actual machine — but still push often rather than batching, so nothing is ever sitting unpushed for long.
5. **Before starting a new task (2, 3, or 5), re-read this context.md in full — especially the stuck log in README.md — rather than starting fresh from a code skim.** An AI assistant picking this up mid-way should treat this file as the source of truth for *decisions already made*, not just re-derive an approach from reading the code, since some of those decisions (like the Tier-3 conflict rule) aren't obvious from the code alone without knowing what was tried and rejected first.

## Repo location & structure

Working locally at `consultbae-merge/` (this needs to be pushed to an actual GitHub repo — that hasn't happened yet, everything so far is local commits only. See the Git & AI workflow section above for how to push it once you have the files locally).

```
consultbae-merge/
├── .gitignore
├── README.md                          # setup steps + Task 1 approach + Task 3 approach + full Task 4 report + stuck log (4 entries)
├── requirements.txt                   # pandas, streamlit, pydub, numpy, pytest
├── packages.txt                       # ffmpeg (system dep, needed for Streamlit Cloud deployment)
├── data/raw/                          # the 3 original CSVs, untouched
│   ├── source1_naukri_applicants.csv
│   ├── source2_gig_workers.csv
│   └── source3_cbnexus_contacts.csv
├── scripts/
│   ├── 01_profile.py                  # profiles raw files, prints issues found (read-only, no writes)
│   ├── 02_build_database.py           # THE core Task 1 pipeline — normalizes, matches, builds db/consultbae.db
│   └── common.py                      # shared normalize_phone/email/city helpers, used by both Task 1 pipeline and Task 3 app
├── app/
│   ├── streamlit_app.py               # Task 3 UI — Submit Recording view + All Submissions view
│   ├── audio_utils.py                 # audio feature extraction (duration/sample rate/bitrate/loudness/noise estimate)
│   └── db_utils.py                    # matches submissions to Task 1's people table via phone number
├── tests/
│   └── test_audio_utils.py            # 5 passing regression tests for the extraction logic
├── uploads/audio/                     # gitignored — where submitted audio files actually get saved
└── db/
    ├── consultbae.db                  # generated SQLite output (untracked in git — see decision below)
    └── merged_people_full_export.csv  # generated flat export for manual review
```

## Git state — IMPORTANT, read before committing anything

Current commits (all local, not pushed anywhere yet):
```
2b0af31 Update README: Task 3 setup steps + approach writeup, stuck log entry #4, repo structure listing
ec68b44 Add Streamlit UI for Task 3
09ff6d1 Add database integration layer for audio app (Task 3 pt.2)
f86c005 Add audio feature extraction module + tests (Task 3 pt.1)
899e6ab Extract shared normalization helpers into common.py for reuse in audio app
4d5a3f1 Add Git & AI workflow guidance to context.md for future commits
4a48c76 Add context.md handoff doc for developer transition
cd8849a Add README with setup steps, Task 1 approach, data issues report (Task 4), and stuck log
f65c7cd Fix match_method mislabeling
4537869 Add profiling script + entity-resolution merge pipeline
c54e3ef Add raw source CSVs
```
(run `git log --oneline` yourself for the authoritative current list — this file will drift out of date as more commits land)

**Uncommitted / undecided right now:**
- `db/` folder — still untracked. Decide and document whether to commit the generated `.db` file (convenient for reviewers to open directly) or gitignore it and rely on the build script (cleaner, but reviewer has to run the pipeline first). Either is defensible — just pick one and note the reasoning in the README.

**Immediate next action:** start Task 2 (n8n automation) — see below.

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

## Task 3 — audio app (DONE, committed)

Built and verified end to end. Stack: **Streamlit + pydub/ffmpeg + numpy**, both browser recording (`st.audio_input`) and file upload (`st.file_uploader`) supported as required.

**Files added:**
- `app/streamlit_app.py` — the UI (two views: Submit Recording, All Submissions)
- `app/audio_utils.py` — extraction logic (duration, sample rate, bitrate, loudness, noise estimate)
- `app/db_utils.py` — links submissions to the Task 1 `people` table via `norm_phone()` from `scripts/common.py`
- `tests/test_audio_utils.py` — 5 passing regression tests
- `packages.txt` — added for Streamlit Cloud deployment (`ffmpeg` system dependency)
- `requirements.txt` — updated with `streamlit`, `pydub`, `numpy`, `pytest`

**Key decisions already made (don't re-derive, just read `README.md`'s Task 3 section for full detail):**
- Bitrate is computed as *effective bitrate* (file size / duration), not parsed encoder metadata — deliberate, documented tradeoff, validated against a known 128kbps mp3 (came back 132.6kbps, close enough to trust).
- Loudness is dBFS via `pydub`'s `.dBFS`; `-inf` (silence) is explicitly caught and stored as `NULL`, not a raw float.
- Noise estimate is a short-time RMS percentile heuristic (10th percentile ≈ noise floor, 90th ≈ signal, ratio in dB ≈ SNR), bucketed into Clean/Some noise/Noisy. **A real bug was caught testing this** — see README stuck log entry #4 before touching this function again. Short version: it only works on signals with natural quiet/loud variation (like real speech with pauses); a continuous tone breaks it, and that's now a documented, tested limitation, not a hidden one.
- On submit, phone number is normalized and matched against `people.primary_phone`. Match → links to existing `person_id`. No match → creates a new person with `matched_sources='audio_app'`. Verified both paths against the real DB (existing: Tanvi Gupta → person_id 1; new: Rakesh Kumar → person_id 56).
- Audio files save to `uploads/audio/` (gitignored — don't commit real recordings).

**Known risk — already hit and fixed, keep the fix in place:** `pydub` depends on the stdlib `audioop` module, deprecated in Python 3.12 and **removed entirely in Python 3.13**. This wasn't theoretical — it broke immediately on the person's actual local machine (Python 3.13, Windows), with `ModuleNotFoundError: No module named 'audioop'` then `'pyaudioop'` on the fallback path. Fix: `pip install audioop-lts` (the official backport, restores the `audioop` module by that exact import name). This is now baked into `requirements.txt` as `audioop-lts>=0.2; python_version >= "3.13"` (a conditional/environment-marker dependency — only installs on 3.13+, doesn't affect 3.12 environments like this dev sandbox), and documented as a "known gotcha" in the README setup section. **Don't remove this dependency line** even though it won't be exercised in a 3.12 dev/test environment — it's there for whoever's actual machine is on 3.13+, which is increasingly likely to be most people's default going forward given how recently 3.13 shipped.

**Verified before moving on:** full pipeline re-run (`02_build_database.py`) still gives 55 people with `audio_submissions` empty/clean after test data was cleared; `pytest tests/test_audio_utils.py` passes 5/5; Streamlit app boots headlessly with HTTP 200 and no import errors (UI itself wasn't clicked through in a real browser in this session — worth doing an actual manual click-through pass before recording the video).

## Task 2 — n8n automation (NOT STARTED, this is where to resume)

Plan discussed: lean toward the **LLM auto-tagging flow** (n8n → reads a person's `skills`/`skill_tags` field from the database → Claude API call to classify into a skill category like "automation-heavy" / "web dev" / "data" → writes the tag back to the database) rather than the duplicate-alert flow, since it better showcases real automation-stack experience. Not yet built. Should be built **after** Task 3 so it has a real audio-app-fed database to connect to. Remember: **pure-code solutions score zero here** — must actually be built in n8n (or Make/Zapier) and the flow JSON exported into the repo, with the run shown in the video.

## Task 5 — scaling stretch doc (NOT STARTED)

One-pager, no code. Needs to cover: what breaks first at 5,000 concurrent gig worker submissions over a weekend (local disk storage won't survive a redeploy — needs object storage like S3; SQLite write contention under concurrent load — would need to swap to Postgres; synchronous audio processing blocking uploads — needs a queue; duplicate submission handling; idempotency/retries; rough cost estimate). Should be written last, after Task 3 is actually built, so it can reference real bottlenecks in the actual implementation rather than being generic.

## Final steps not yet done (after all 5 tasks)

- Push the local repo to an actual GitHub repository (hasn't happened — everything is local commits so far).
- Deploy the Streamlit app somewhere free (Render/Streamlit Cloud) OR plan to demo it running locally in the screen recording.
- Record the ≤6min Loom/screen recording: run the Task 1 pipeline, show the audio app end-to-end, walk through the 2-3 hardest decisions (the Arjun Mehta merge bug is the strongest one to walk through on camera — it's specific and shows real debugging, not just "I used AI to generate code").
