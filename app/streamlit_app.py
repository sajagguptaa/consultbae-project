"""
Task 3 — mini audio collection app.

Two views (sidebar navigation):
  1. "Submit Recording" - name + phone form, browser mic recording OR file
     upload (both supported per requirement), auto-extracts audio properties
     on submit and writes to the same database Task 1 built.
  2. "All Submissions"   - lists every submission with a play button and its
     extracted properties.

Run locally with: streamlit run app/streamlit_app.py
"""
import subprocess
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from audio_utils import analyze_audio
from db_utils import save_submission, list_submissions, db_exists

st.set_page_config(page_title="ConsultBae Audio Collection", page_icon="🎙️", layout="centered")

REPO_ROOT = Path(__file__).parent.parent

if not db_exists():
    # db/consultbae.db is a generated build artifact, deliberately not committed
    # to git (see context.md for the reasoning). On a fresh deploy (e.g. Streamlit
    # Cloud cloning the repo from scratch), it won't exist yet - rather than show
    # a dead error screen, build it automatically from the raw CSVs that ARE in
    # the repo. This runs scripts/02 and 03 exactly as documented in the README,
    # just triggered on first load instead of requiring a manual step beforehand.
    with st.spinner("First run — building the database from the source CSVs (Task 1 pipeline)..."):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "02_build_database.py")],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            st.error(f"Database build failed:\n```\n{result.stderr}\n```")
            st.stop()
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "03_add_skill_category_column.py")],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )

st.sidebar.title("🎙️ ConsultBae Audio")
page = st.sidebar.radio("View", ["Submit Recording", "All Submissions"])

# ---------------------------------------------------------------------------
# VIEW 1: Submit Recording
# ---------------------------------------------------------------------------
if page == "Submit Recording":
    st.title("Submit a Recording")
    st.caption("Enter your details, then either record directly in the browser or upload an audio file.")

    with st.form("submission_form", clear_on_submit=False):
        name = st.text_input("Full name")
        phone = st.text_input("Phone number", placeholder="e.g. 9000000254")

        st.markdown("**Record in browser**")
        recorded = st.audio_input("Record audio")

        st.markdown("**— or —**")
        uploaded = st.file_uploader(
            "Upload an audio file", type=["wav", "mp3", "m4a", "ogg", "flac"]
        )

        submitted = st.form_submit_button("Submit")

    if submitted:
        if not name.strip():
            st.error("Please enter your name.")
        elif not phone.strip():
            st.error("Please enter your phone number.")
        elif not recorded and not uploaded:
            st.error("Please either record audio in the browser or upload a file.")
        else:
            # Prefer the browser recording if both were somehow provided
            if recorded is not None:
                audio_bytes = recorded.getvalue()
                file_ext = "wav"  # st.audio_input always produces WAV
                source_label = "browser recording"
            else:
                audio_bytes = uploaded.getvalue()
                file_ext = Path(uploaded.name).suffix.lstrip(".").lower() or "wav"
                source_label = f"uploaded file ({uploaded.name})"

            with st.spinner("Extracting audio properties..."):
                try:
                    features = analyze_audio(audio_bytes, f"audio.{file_ext}")
                except Exception as e:
                    st.error(f"Couldn't process this audio file: {e}")
                    st.stop()

                submission_id, person_id, is_new = save_submission(
                    name, phone, audio_bytes, file_ext, features
                )

            st.success(f"Submitted successfully from {source_label}!")
            if is_new:
                st.info(f"New person created in the database (person_id {person_id}).")
            else:
                st.info(f"Matched to an existing person in the database (person_id {person_id}) via phone number.")

            st.subheader("Extracted properties")
            c1, c2 = st.columns(2)
            c1.metric("Duration", f"{features['duration_sec']} sec")
            c1.metric("Sample rate", f"{features['sample_rate_khz']} kHz")
            c2.metric("Bitrate", f"{features['bitrate_kbps']} kbps" if features["bitrate_kbps"] else "—")
            c2.metric("Loudness", f"{features['loudness_db']} dB" if features["loudness_db"] is not None else "Silent")
            st.write(f"**Noise/quality estimate:** {features['noise_estimate']}")

# ---------------------------------------------------------------------------
# VIEW 2: All Submissions
# ---------------------------------------------------------------------------
else:
    st.title("All Submissions")
    submissions = list_submissions()

    if not submissions:
        st.info("No submissions yet — go to 'Submit Recording' to add one.")
    else:
        st.caption(f"{len(submissions)} submission(s)")
        for s in submissions:
            with st.container(border=True):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.markdown(f"**{s['submitted_name']}** — {s['submitted_phone']}")
                    st.caption(f"Submitted {s['created_at']} · person_id {s['person_id']} ({s['matched_sources']})")
                with col2:
                    st.write(f"Duration: {s['duration_sec']}s")
                    st.write(f"Sample rate: {round(s['sample_rate_hz']/1000, 1)} kHz")

                st.write(
                    f"Bitrate: {s['bitrate_kbps']} kbps | "
                    f"Loudness: {s['loudness_db']} dB | "
                    f"Quality: {s['noise_estimate']}"
                )

                audio_path = Path(s["file_path"])
                if audio_path.exists():
                    st.audio(str(audio_path))
                else:
                    st.warning("Audio file missing from disk.")
