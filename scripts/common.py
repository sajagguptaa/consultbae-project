"""
Shared normalization helpers, used by both scripts/02_build_database.py (Task 1)
and app/streamlit_app.py (Task 3).

Why this exists as its own module: the audio app needs to match a submitted
phone number against the SAME people table Task 1 built, using the SAME
normalization rules. Duplicating norm_phone() in two places is exactly the
kind of thing that quietly drifts out of sync later (e.g. someone tweaks the
matching threshold in one place and forgets the other) - so both entry points
import from here instead.
"""
import re
import pandas as pd

CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru",
    "gurgaon": "Gurugram", "gurugram": "Gurugram",
    "noida": "Noida",
    "pune": "Pune",
    "delhi": "Delhi", "new delhi": "Delhi",
    "delhi ncr": "Delhi NCR",
}

def norm_city(c):
    if c is None or (isinstance(c, float) and pd.isna(c)):
        return None
    key = str(c).strip().lower()
    return CITY_ALIASES.get(key, str(c).strip().title())

def norm_email(e):
    if e is None or (isinstance(e, float) and pd.isna(e)) or "@" not in str(e):
        return None
    return str(e).strip().lower()

def norm_phone(p):
    """Strip all non-digits, return last 10 digits - the canonical Indian mobile
    number, regardless of whether the input had a +91 / 0 / 91 prefix or not."""
    if p is None or (isinstance(p, float) and pd.isna(p)):
        return None
    digits = re.sub(r"\D", "", str(p))
    if len(digits) < 10:
        return None
    return digits[-10:]

def norm_name_key(n):
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return None
    return re.sub(r"\s+", " ", str(n).strip().lower().replace(".", ""))
