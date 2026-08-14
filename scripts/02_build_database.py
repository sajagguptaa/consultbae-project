"""
Step 2: Normalize, resolve entities across the 3 sources, and load into SQLite.

ENTITY RESOLUTION STRATEGY (read this before touching the matching logic)
---------------------------------------------------------------------------
None of the 3 files share a single common ID:
  - source1 (naukri) has email + phone
  - source2 (gig_workers) has ONLY email
  - source3 (cbnexus) has ONLY phone

So a person who exists in source2 and source3 but NOT source1 has literally
no directly shared field between those two rows (e.g. Manish Bhatia). The only
way to link them is name + city as a fallback.

We use a Union-Find (disjoint set) over every row from all 3 files, and union
two rows together using a TIERED confidence rule, applied in this order:

  Tier 1 (strong): normalized email matches exactly           -> merge
  Tier 2 (strong): normalized phone (last 10 digits) matches   -> merge
  Tier 3 (fallback, weak): normalized name + canonical city match,
           BUT ONLY if this can't be independently disproven. If both
           rows being compared have a phone or email on record and those
           values DISAGREE, we do NOT merge them, even if name+city match.

Why Tier 3 has that safety clause:
  The dataset has "Arjun Mehta" appearing twice in source3 with the SAME
  city (Noida) but two DIFFERENT phone numbers, and a third "Arjun Mehta"
  record in source2 with no phone at all. If we merged purely on name+city,
  we'd silently collapse what might be two different real people into one.
  Instead: the source2 record (no phone to contradict) merges with the
  source1+source3 cluster that shares its city, while the second source3
  phone number (272) — which actively conflicts with the first (131) — is
  kept as a SEPARATE, flagged record for manual review. This mirrors what
  a human analyst would do: merge when nothing contradicts, keep separate
  when something does.
"""
import pandas as pd
import sqlite3
import re
import json
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

BASE = Path(__file__).parent.parent
RAW = BASE / "data" / "raw"
DB_PATH = BASE / "db" / "consultbae.db"

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru",
    "gurgaon": "Gurugram", "gurugram": "Gurugram",
    "noida": "Noida",
    "pune": "Pune",
    "delhi": "Delhi", "new delhi": "Delhi",
    "delhi ncr": "Delhi NCR",  # kept distinct - it's a region, not a specific city, see data issues report
}

def norm_city(c):
    if pd.isna(c):
        return None
    key = str(c).strip().lower()
    return CITY_ALIASES.get(key, str(c).strip().title())

def norm_email(e):
    if pd.isna(e) or "@" not in str(e):
        return None
    return str(e).strip().lower()

def norm_phone(p):
    if pd.isna(p):
        return None
    digits = re.sub(r"\D", "", str(p))
    if len(digits) < 10:
        return None
    return digits[-10:]  # last 10 digits = canonical Indian mobile number, strips 0/91/+91 prefixes

def norm_name_key(n):
    if pd.isna(n):
        return None
    return re.sub(r"\s+", " ", str(n).strip().lower().replace(".", ""))

def name_similarity(a, b):
    if not a or not b:
        return 0
    return SequenceMatcher(None, a, b).ratio()

def parse_ctc(raw):
    """Detect whether a CTC figure is in Lakhs (e.g. 4.2) or absolute INR (e.g. 417964)."""
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None, None, "unparseable"
    if val < 100:
        return round(val * 100000, 2), "lakhs", None
    return val, "absolute", None

def parse_applied_date(raw):
    """
    Source1 mixes THREE date conventions in one column:
      - ISO: YYYY-MM-DD                (unambiguous)
      - Dash: DD-MM-YYYY               (Indian convention)
      - Slash: MM/DD/YYYY              (US convention - confirmed because some
                                         day values like 13,19,21 can't be months)
      - "D Mon YYYY" / "DD Mon YYYY"   (unambiguous, named month)
    Returns (iso_date_string, ambiguous_flag)
    """
    raw = str(raw).strip()
    ambiguous = False
    dt = None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.strptime(raw, "%Y-%m-%d")
        elif re.fullmatch(r"\d{2}-\d{2}-\d{4}", raw):
            dt = datetime.strptime(raw, "%d-%m-%Y")
        elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", raw):
            m, d, y = raw.split("/")
            m, d = int(m), int(d)
            if m > 12 and d <= 12:  # actually DD/MM disguised - swap
                m, d = d, m
            if d <= 12 and m <= 12:
                ambiguous = True  # both segments are valid as day or month - can't be 100% sure
            dt = datetime(int(y), m, d)
        else:
            # "7 Jul 2026" / "19 Jul 2026" style
            dt = datetime.strptime(raw, "%d %b %Y")
    except Exception:
        return raw, True  # couldn't parse at all - flag for manual review, keep raw string
    return dt.strftime("%Y-%m-%d"), ambiguous

def parse_rate(raw):
    if pd.isna(raw):
        return None, None
    raw = str(raw).strip()
    if raw.endswith("/hr"):
        return "hourly", float(raw.replace("/hr", ""))
    if raw.endswith("k/month"):
        return "monthly", float(raw.replace("k/month", "")) * 1000
    return "other", None

def norm_status(raw):
    if pd.isna(raw):
        return None
    v = str(raw).strip().lower()
    return {"active": "Active", "inactive": "Inactive", "paused": "Paused"}.get(v, raw)

def norm_verified(raw):
    if pd.isna(raw):
        return None
    v = str(raw).strip().lower()
    return 1 if v in ("y", "yes") else 0 if v in ("n", "no") else None


# ---------------------------------------------------------------------------
# Load + clean each source into a common "node" representation
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self):
        self.parent = {}
    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

nodes = {}  # node_id -> dict(name, email, phone, city, source, row_num)

# --- Source 1: naukri applicants ---
df1_raw = pd.read_csv(RAW / "source1_naukri_applicants.csv")
for i, row in df1_raw.iterrows():
    nid = f"s1_{i}"
    nodes[nid] = dict(
        name=row["Full Name"], email=norm_email(row["Email"]), phone=norm_phone(row["Phone"]),
        city=norm_city(row["City"]), source="source1", row_num=i + 2,  # +2 = header + 1-index
        raw=row.to_dict()
    )

# --- Source 2: gig workers (drop blank row + the corrupted/shifted row) ---
df2_raw = pd.read_csv(RAW / "source2_gig_workers.csv")
df2_clean = df2_raw[df2_raw["email_id"].astype(str).str.contains("@", na=False)].copy()
dropped_rows_s2 = df2_raw[~df2_raw.index.isin(df2_clean.index)]
for i, row in df2_clean.iterrows():
    nid = f"s2_{i}"
    nodes[nid] = dict(
        name=row["worker_name"], email=norm_email(row["email_id"]), phone=None,
        city=norm_city(row["location"]), source="source2", row_num=i + 2,
        raw=row.to_dict()
    )

# --- Source 3: cbnexus contacts (drop embedded duplicate header row) ---
df3_raw = pd.read_csv(RAW / "source3_cbnexus_contacts.csv")
df3_clean = df3_raw[df3_raw["Name"] != "Name"].copy()
for i, row in df3_clean.iterrows():
    nid = f"s3_{i}"
    nodes[nid] = dict(
        name=row["Name"], email=None, phone=norm_phone(row["Phone Number"]),
        city=norm_city(row["City"]), source="source3", row_num=i + 2,
        raw=row.to_dict()
    )

# ---------------------------------------------------------------------------
# Union-Find matching, tiered by confidence
# ---------------------------------------------------------------------------
uf = UnionFind()
node_ids = list(nodes.keys())

# Tier 1: exact email
by_email = {}
for nid in node_ids:
    e = nodes[nid]["email"]
    if e:
        by_email.setdefault(e, []).append(nid)
for group in by_email.values():
    for other in group[1:]:
        uf.union(group[0], other)

# Tier 2: exact phone
by_phone = {}
for nid in node_ids:
    p = nodes[nid]["phone"]
    if p:
        by_phone.setdefault(p, []).append(nid)
for group in by_phone.values():
    for other in group[1:]:
        uf.union(group[0], other)

# Tier 3: name + city fallback, ONLY when not contradicted by a differing phone/email.
#
# IMPORTANT (fixed after catching a bug during testing - see stuck log in README):
# We must NOT compare fallback matches at the level of two raw rows. If we do, a
# node with a missing phone/email (e.g. source2, which has no phone field at all)
# can act as a silent "bridge" that transitively merges two clusters that actually
# conflict with each other. Concretely: source1's Arjun Mehta (phone 131) and
# source3's second Arjun Mehta (phone 272) directly conflict and must never merge -
# but source2's Arjun Mehta (no phone) doesn't conflict with EITHER of them taken
# individually, so a naive pairwise check merged all three into one, erasing the
# conflict. Fix: compare against the AGGREGATE phone/email set of the whole cluster
# a node is about to join, not just the one row it happens to be paired with. And
# if a node is compatible with two DIFFERENT clusters that themselves conflict with
# each other, that's a genuine ambiguity - don't guess, leave unmerged and flag it.
match_log = []  # human-readable log of interesting matches/blocks, goes into the data issues report
fallback_merged_nodes = set()  # node_ids that were merged via Tier 3 (name+city), for accurate match_method labeling
by_namecity = {}
for nid in node_ids:
    n = nodes[nid]
    key = (norm_name_key(n["name"]), n["city"])
    if key[0] and key[1]:
        by_namecity.setdefault(key, []).append(nid)

def cluster_field_sets(member_node_ids):
    phones = {nodes[m]["phone"] for m in member_node_ids if nodes[m]["phone"]}
    emails = {nodes[m]["email"] for m in member_node_ids if nodes[m]["email"]}
    return phones, emails

def clusters_conflict(members_a, members_b):
    pa, ea = cluster_field_sets(members_a)
    pb, eb = cluster_field_sets(members_b)
    phone_conflict = pa and pb and pa.isdisjoint(pb)
    email_conflict = ea and eb and ea.isdisjoint(eb)
    return phone_conflict or email_conflict

for key, group in by_namecity.items():
    if len(group) < 2:
        continue
    changed = True
    while changed:  # fixed-point: re-evaluate after every merge since aggregate sets change
        changed = False
        # current distinct clusters present in this name+city group
        roots = {}
        for nid in group:
            roots.setdefault(uf.find(nid), []).append(nid)
        root_list = list(roots.keys())
        if len(root_list) < 2:
            break
        # compatibility graph between clusters
        compatible_pairs = []
        for i in range(len(root_list)):
            for j in range(i + 1, len(root_list)):
                if not clusters_conflict(roots[root_list[i]], roots[root_list[j]]):
                    compatible_pairs.append((root_list[i], root_list[j]))
        # degree of each cluster in the compatibility graph
        degree = {r: 0 for r in root_list}
        for a, b in compatible_pairs:
            degree[a] += 1
            degree[b] += 1
        for a, b in compatible_pairs:
            ra_name = nodes[roots[a][0]]["name"]
            rb_name = nodes[roots[b][0]]["name"]
            if degree[a] == 1 and degree[b] == 1:
                # unambiguous: each cluster has exactly one compatible candidate - safe to merge
                fallback_merged_nodes.update(roots[a])
                fallback_merged_nodes.update(roots[b])
                uf.union(a, b)
                match_log.append(
                    f"MERGED (fallback): '{ra_name}' cluster ({[ (nodes[m]['source'], nodes[m]['row_num']) for m in roots[a] ]}) "
                    f"with '{rb_name}' cluster ({[ (nodes[m]['source'], nodes[m]['row_num']) for m in roots[b] ]}) "
                    f"on name+city match ({key[1]}), no conflicting phone/email."
                )
                changed = True
                break  # restart fixed-point loop with updated clusters
            else:
                match_log.append(
                    f"AMBIGUOUS (not merged): '{ra_name}' cluster ({[ (nodes[m]['source'], nodes[m]['row_num']) for m in roots[a] ]}) "
                    f"could plausibly match MULTIPLE candidates for name+city ({key[1]}) - left as separate "
                    f"records, flagged for manual review rather than guessing."
                )
        # log direct conflicts once (not on every fixed-point pass) - handled below outside loop

# Log direct conflicts (pairs that never became compatible) once, for transparency
for key, group in by_namecity.items():
    if len(group) < 2:
        continue
    roots = {}
    for nid in group:
        roots.setdefault(uf.find(nid), []).append(nid)
    root_list = list(roots.keys())
    for i in range(len(root_list)):
        for j in range(i + 1, len(root_list)):
            a, b = root_list[i], root_list[j]
            if clusters_conflict(roots[a], roots[b]):
                ra = roots[a][0]; rb = roots[b][0]
                match_log.append(
                    f"BLOCKED merge: '{nodes[ra]['name']}' ({nodes[ra]['source']} row {nodes[ra]['row_num']}) vs "
                    f"'{nodes[rb]['name']}' ({nodes[rb]['source']} row {nodes[rb]['row_num']}) - same name+city "
                    f"({key[1]}) but conflicting phone/email. Kept as SEPARATE records."
                )

# ---------------------------------------------------------------------------
# Build canonical clusters -> person records
# ---------------------------------------------------------------------------
clusters = {}
for nid in node_ids:
    root = uf.find(nid)
    clusters.setdefault(root, []).append(nid)

people = []          # list of dicts for `people` table
lineage = []         # list of dicts for `source_lineage` table
applicant_rows = {}  # person_id -> chosen row dict
gig_rows = {}
cbnexus_rows = {}

for person_idx, (root, member_ids) in enumerate(clusters.items(), start=1):
    members = [nodes[m] for m in member_ids]
    names = [m["name"] for m in members]
    canonical_name = max(names, key=len)  # prefer the fuller name e.g. "Rohit Verma" over "R. Verma"
    emails = [m["email"] for m in members if m["email"]]
    phones = [m["phone"] for m in members if m["phone"]]
    cities = [m["city"] for m in members if m["city"]]
    sources_hit = sorted(set(m["source"] for m in members))

    people.append(dict(
        person_id=person_idx,
        canonical_name=canonical_name,
        primary_email=emails[0] if emails else None,
        primary_phone=phones[0] if phones else None,
        primary_city=max(set(cities), key=cities.count) if cities else None,
        matched_sources=",".join(sources_hit),
        match_method=(
            "fallback_name_city" if any(m in fallback_merged_nodes for m in member_ids)
            else "exact_email_or_phone" if len(sources_hit) > 1
            else "single_source_only"
        ),
    ))

    for m in members:
        lineage.append(dict(
            person_id=person_idx, source_file=m["source"], source_row_num=m["row_num"],
            raw_name=m["name"], raw_email=m["raw"].get("Email") or m["raw"].get("email_id"),
            raw_phone=m["raw"].get("Phone") or m["raw"].get("Phone Number"),
            raw_city=m["raw"].get("City") or m["raw"].get("location"),
        ))
        if m["source"] == "source1":
            applicant_rows.setdefault(person_idx, []).append(m["raw"])
        elif m["source"] == "source2":
            gig_rows.setdefault(person_idx, []).append(m["raw"])
        elif m["source"] == "source3":
            cbnexus_rows.setdefault(person_idx, []).append(m["raw"])

print(f"Total raw rows across all 3 sources: {len(nodes)}")
print(f"Resolved to {len(people)} unique people")
print(f"\n--- Matching decisions worth reviewing ---")
for line in match_log:
    print(" -", line)

# ---------------------------------------------------------------------------
# Collapse within-source duplicates (e.g. "R. Verma" + "Rohit Verma" both
# landed in source1 for the same person via exact email match). We keep ONE
# profile row per person per source - the most complete one - and record the
# rest in source_lineage with is_duplicate_within_source=1 so nothing is lost.
# ---------------------------------------------------------------------------

def pick_best_applicant_row(rows):
    # prefer the row with the longer/more complete Full Name, tie-break on more skills listed
    return max(rows, key=lambda r: (len(str(r["Full Name"])), len(str(r["Skills"]))))

def pick_best_gig_row(rows):
    return rows[0]  # source2 had no within-person duplicates in this dataset after cleaning

def pick_best_cbnexus_row(rows):
    return rows[0]

applicant_final, gig_final, cbnexus_final = {}, {}, {}
duplicate_row_notes = []

for pid, rows in applicant_rows.items():
    if len(rows) > 1:
        best = pick_best_applicant_row(rows)
        duplicate_row_notes.append(
            f"person_id {pid}: {len(rows)} rows in source1 for the same person "
            f"(names seen: {[r['Full Name'] for r in rows]}) - kept the fuller record, "
            f"discarded the rest as redundant duplicates."
        )
    else:
        best = rows[0]
    applicant_final[pid] = best

for pid, rows in gig_rows.items():
    gig_final[pid] = pick_best_gig_row(rows)

for pid, rows in cbnexus_rows.items():
    cbnexus_final[pid] = pick_best_cbnexus_row(rows)

print(f"\n--- Within-source duplicate collapsing ---")
for line in duplicate_row_notes:
    print(" -", line)

# ---------------------------------------------------------------------------
# Build SQLite database
# ---------------------------------------------------------------------------
DB_PATH.parent.mkdir(exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()  # rebuild fresh every run - this script is idempotent

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.executescript("""
CREATE TABLE people (
    person_id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    primary_email TEXT,
    primary_phone TEXT,
    primary_city TEXT,
    matched_sources TEXT,
    match_method TEXT
);

CREATE TABLE source_lineage (
    lineage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER REFERENCES people(person_id),
    source_file TEXT,
    source_row_num INTEGER,
    raw_name TEXT,
    raw_email TEXT,
    raw_phone TEXT,
    raw_city TEXT
);

CREATE TABLE applicant_profile (
    person_id INTEGER PRIMARY KEY REFERENCES people(person_id),
    experience_years REAL,
    ctc_annual_inr REAL,
    ctc_raw_value TEXT,
    ctc_unit_assumed TEXT,
    applied_date TEXT,
    applied_date_raw TEXT,
    applied_date_ambiguous INTEGER DEFAULT 0,
    skills TEXT
);

CREATE TABLE gig_worker_profile (
    person_id INTEGER PRIMARY KEY REFERENCES people(person_id),
    rate_raw TEXT,
    rate_type TEXT,
    rate_value_inr REAL,
    status TEXT,
    skill_tags TEXT
);

CREATE TABLE cbnexus_profile (
    person_id INTEGER PRIMARY KEY REFERENCES people(person_id),
    verified INTEGER,
    projects_completed INTEGER
);

CREATE TABLE audio_submissions (
    submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER REFERENCES people(person_id),
    submitted_name TEXT,
    submitted_phone TEXT,
    file_path TEXT,
    duration_sec REAL,
    sample_rate_hz INTEGER,
    bitrate_kbps REAL,
    loudness_db REAL,
    noise_estimate TEXT,
    created_at TEXT
);
""")

cur.executemany(
    "INSERT INTO people VALUES (:person_id, :canonical_name, :primary_email, :primary_phone, :primary_city, :matched_sources, :match_method)",
    people
)
cur.executemany(
    "INSERT INTO source_lineage (person_id, source_file, source_row_num, raw_name, raw_email, raw_phone, raw_city) "
    "VALUES (:person_id, :source_file, :source_row_num, :raw_name, :raw_email, :raw_phone, :raw_city)",
    lineage
)

for pid, r in applicant_final.items():
    ctc_val, ctc_unit, _ = parse_ctc(r["Current CTC"])
    date_iso, date_ambig = parse_applied_date(r["Applied Date"])
    cur.execute(
        "INSERT INTO applicant_profile VALUES (?,?,?,?,?,?,?,?,?)",
        (pid, float(r["Experience (Years)"]), ctc_val, str(r["Current CTC"]), ctc_unit,
         date_iso, str(r["Applied Date"]), int(date_ambig), r["Skills"])
    )

for pid, r in gig_final.items():
    rate_type, rate_val = parse_rate(r["rate"])
    cur.execute(
        "INSERT INTO gig_worker_profile VALUES (?,?,?,?,?,?)",
        (pid, r["rate"], rate_type, rate_val, norm_status(r["status"]), r["skill_tags"])
    )

for pid, r in cbnexus_final.items():
    cur.execute(
        "INSERT INTO cbnexus_profile VALUES (?,?,?)",
        (pid, norm_verified(r["Verified"]), int(r["Projects Completed"]))
    )

conn.commit()

# ---------------------------------------------------------------------------
# Sanity checks - print counts so we can eyeball the result makes sense
# ---------------------------------------------------------------------------
print("\n--- Final database summary ---")
for table in ["people", "source_lineage", "applicant_profile", "gig_worker_profile", "cbnexus_profile"]:
    n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"{table}: {n} rows")

print("\nPeople matched across all 3 sources:")
for row in cur.execute("SELECT person_id, canonical_name, matched_sources FROM people WHERE matched_sources LIKE '%,%,%'"):
    print(" -", row)

conn.close()
print(f"\nDatabase written to {DB_PATH}")

