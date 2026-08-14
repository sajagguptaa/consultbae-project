"""
Step 1: Profile the 3 raw source files BEFORE deciding how to clean/merge them.

Why profile first instead of jumping to cleaning code:
  - We want evidence, not guesses, for the Data Issues Report (Task 4).
  - Cleaning decisions (e.g. how to normalize phone numbers) should be driven by
    what's actually in the data, not assumptions.

This script does NOT modify anything. It only reads and prints findings.
"""
import pandas as pd
import re
from pathlib import Path

RAW = Path(__file__).parent.parent / "data" / "raw"

def hr(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def profile_source1():
    hr("SOURCE 1 — naukri_applicants.csv")
    df = pd.read_csv(RAW / "source1_naukri_applicants.csv")
    print("Shape:", df.shape)
    print("Columns:", list(df.columns))

    # Phone format inconsistency
    phone_formats = df["Phone"].astype(str).apply(
        lambda x: "starts_+91" if x.startswith("+91")
        else "starts_0" if x.startswith("0")
        else "10digit_plain" if re.fullmatch(r"\d{10}", x)
        else "other"
    ).value_counts()
    print("\nPhone number format distribution:\n", phone_formats)

    # City casing / whitespace inconsistency
    print("\nDistinct raw City values (note casing/whitespace/naming variants):")
    print(sorted(df["City"].unique()))

    # CTC unit inconsistency: some values look like lakhs (e.g. 4.2), some like
    # absolute rupees (e.g. 417964). A CTC of "4.2" is nonsensical as rupees,
    # but a CTC of "417964" is nonsensical as lakhs (41 crore).
    ctc = pd.to_numeric(df["Current CTC"], errors="coerce")
    small = (ctc < 100).sum()
    large = (ctc >= 100).sum()
    print(f"\nCurrent CTC: {small} rows look like LAKHS (<100), {large} rows look like ABSOLUTE RUPEES (>=100)")
    print("Sample small values:", ctc[ctc < 100].head(5).tolist())
    print("Sample large values:", ctc[ctc >= 100].head(5).tolist())

    # Date format inconsistency
    print("\nSample raw Applied Date values (mixed formats):")
    print(df["Applied Date"].head(10).tolist())

    # Duplicate people by email
    dupe_emails = df["Email"].str.lower().value_counts()
    dupe_emails = dupe_emails[dupe_emails > 1]
    print("\nEmails appearing more than once within source1:\n", dupe_emails)

    # Duplicate people by phone (normalized)
    norm_phone = df["Phone"].astype(str).str.replace(r"\D", "", regex=True).str[-10:]
    dupe_phones = norm_phone.value_counts()
    dupe_phones = dupe_phones[dupe_phones > 1]
    print("\nNormalized phones appearing more than once within source1:\n", dupe_phones)
    if len(dupe_phones):
        for p in dupe_phones.index:
            print(df[norm_phone == p][["Full Name", "Email", "Phone", "City"]])

    return df


def profile_source2():
    hr("SOURCE 2 — gig_workers.csv")
    df = pd.read_csv(RAW / "source2_gig_workers.csv")
    print("Shape:", df.shape)
    print("Columns:", list(df.columns))

    # Fully blank row
    blank_rows = df[df.isna().all(axis=1)]
    print(f"\nFully blank rows: {len(blank_rows)} (index: {blank_rows.index.tolist()})")

    # Malformed / column-shifted row detection: email_id column should contain '@'
    bad_email_rows = df[~df["email_id"].astype(str).str.contains("@", na=False)]
    print(f"\nRows where email_id column does NOT contain '@' (likely shifted/corrupted row): {len(bad_email_rows)}")
    print(bad_email_rows)

    # Email case inconsistency
    print("\nSample email casing (note UPPERCASE vs lowercase):")
    print(df["email_id"].dropna().head(10).tolist())

    # Rate unit inconsistency (/hr vs k/month)
    rate_units = df["rate"].dropna().astype(str).apply(
        lambda x: "per_hour" if "/hr" in x else "per_month_k" if "k/month" in x else "other"
    ).value_counts()
    print("\nRate unit distribution:\n", rate_units)

    # Status casing / extra category
    print("\nDistinct raw status values:", df["status"].dropna().unique().tolist())

    return df


def profile_source3():
    hr("SOURCE 3 — cbnexus_contacts.csv")
    # Read raw lines first because this file has an embedded repeated header row
    with open(RAW / "source3_cbnexus_contacts.csv") as f:
        lines = f.readlines()
    header = lines[0].strip()
    repeated_header_lines = [i for i, l in enumerate(lines) if l.strip() == header and i != 0]
    print(f"Repeated header row found again at line(s): {repeated_header_lines} "
          f"(looks like two exports were concatenated without stripping the second header)")

    df = pd.read_csv(RAW / "source3_cbnexus_contacts.csv")
    # Drop the embedded header-as-data row for further profiling
    df = df[df["Name"] != "Name"]
    print("Shape after dropping embedded header row:", df.shape)

    # Phone format inconsistency
    phone_formats = df["Phone Number"].astype(str).apply(
        lambda x: "plus91_hyphen" if x.startswith("+91-")
        else "91_prefix_12digit" if re.fullmatch(r"91\d{10}", x)
        else "10digit_plain" if re.fullmatch(r"\d{10}", x)
        else "other"
    ).value_counts()
    print("\nPhone number format distribution:\n", phone_formats)

    # Verified column inconsistency
    print("\nDistinct raw Verified values:", df["Verified"].dropna().unique().tolist())

    # City casing/whitespace
    print("\nDistinct raw City values:")
    print(sorted(df["City"].dropna().unique()))

    # Duplicate name+phone combos (e.g. two different "Arjun Mehta" with different phones)
    name_counts = df["Name"].str.strip().str.lower().value_counts()
    dupe_names = name_counts[name_counts > 1]
    print("\nNames appearing more than once within source3 (need to check if same person or different):\n", dupe_names)
    for n in dupe_names.index:
        print(df[df["Name"].str.strip().str.lower() == n][["Name", "Phone Number", "City", "Projects Completed"]])

    return df


if __name__ == "__main__":
    df1 = profile_source1()
    df2 = profile_source2()
    df3 = profile_source3()

    hr("CROSS-SOURCE CHECK: same name, different identifying details")
    # Arjun Mehta check across all 3
    print("\n--- Arjun Mehta across sources ---")
    print("Source1:", df1[df1["Full Name"] == "Arjun Mehta"][["Full Name", "Email", "Phone", "City"]].to_string(index=False))
    print("Source2:", df2[df2["worker_name"] == "Arjun Mehta"][["worker_name", "email_id", "location"]].to_string(index=False))
    print("Source3:", df3[df3["Name"] == "Arjun Mehta"][["Name", "Phone Number", "City"]].to_string(index=False))

    print("\n--- Deepak Nair across sources ---")
    print("Source1:", df1[df1["Full Name"] == "Deepak Nair"][["Full Name", "Email", "Phone", "City"]].to_string(index=False))
    print("Source2:", df2[df2["worker_name"] == "Deepak Nair"][["worker_name", "email_id", "location"]].to_string(index=False))
    print("Source3:", df3[df3["Name"].str.strip() == "DEEPAK NAIR"][["Name", "Phone Number", "City"]].to_string(index=False))
