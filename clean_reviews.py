"""
Stage 1 of the Weekly Review Digest: clean this week's Canva mobile editor
reviews into a pandas table, one review per row.

Run (one command, from the repo root):
    python clean_reviews.py
    python clean_reviews.py path/to/other_export.csv     # a different week

It reads the export file, prints the starting and kept row counts plus the
cleaned table, and saves:
    output/cleaned_reviews.csv   the cleaned table (input to later stages)
    output/cleaned_reviews.txt   exactly what was printed

RULES
-----
Blank review
    A row is blank if review_text is missing, or contains no letter or digit
    once whitespace is ignored ("", "    ", "...", "😡"). A blank row has
    nothing to count under a theme and nothing to quote, so it is dropped.
    A missing review_title alone does NOT make a row blank.

Duplicate review
    A row is a duplicate if every column (store, review_date, star_rating,
    app_version, device_model, platform_os, review_title, review_text)
    matches an earlier row. For the comparison only, text is trimmed,
    lower-cased and its internal whitespace collapsed. The first occurrence
    is kept. This removes the same review exported twice, but keeps two
    different users who happen to write similar words (they differ in date,
    store, device, etc.) because each one is a real mention.

Stable ID
    review_id = "rv_" + the first 10 hex characters of the SHA-1 of that same
    normalised set of columns. It depends only on the review's own content,
    not on row position, so it is identical on every run and does not change
    if rows are reordered or new rows are added. Kept rows can't collide,
    because two rows with the same key are duplicates and only one is kept.

The review_text itself is kept exactly as in the export (only leading and
trailing whitespace is trimmed) so later quotes can be matched word for word.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

import pandas as pd

DEFAULT_EXPORT = Path("data/Canva_Mobile_Editor_Review_Export_2-8_June_2025.csv")
TEXT_COL = "review_text"


def normalise(value) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def is_blank(text) -> bool:
    if pd.isna(text):
        return True
    return re.search(r"[^\W_]", str(text)) is None  # no letter or digit


def clean(export_path: Path):
    raw = pd.read_csv(export_path, dtype=str, keep_default_na=True)
    if TEXT_COL not in raw.columns:
        sys.exit(f"No '{TEXT_COL}' column in {export_path}. Columns: {list(raw.columns)}")
    key_cols = list(raw.columns)
    start = len(raw)

    # Rule 1: blank reviews
    blank_mask = raw[TEXT_COL].apply(is_blank)
    blanks = raw[blank_mask]
    df = raw[~blank_mask].copy()
    df[TEXT_COL] = df[TEXT_COL].str.strip()

    # Stable key (also used for the ID)
    df["_key"] = df[key_cols].apply(lambda r: "\x1f".join(normalise(v) for v in r), axis=1)

    # Rule 2: duplicates (keep first)
    dup_mask = df["_key"].duplicated(keep="first")
    dups = df[dup_mask]
    df = df[~dup_mask].copy()

    # Rule 3: stable ID
    df.insert(0, "review_id", df["_key"].map(
        lambda k: "rv_" + hashlib.sha1(k.encode("utf-8")).hexdigest()[:10]))
    df = df.drop(columns="_key").reset_index(drop=True)

    stats = {
        "start": start,
        "blank": len(blanks),
        "blank_rows": [i + 2 for i in blanks.index],   # +2 = header + 1-based line
        "dup": len(dups),
        "dup_rows": [i + 2 for i in dups.index],
        "kept": len(df),
    }
    return df, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("export", nargs="?", type=Path, default=DEFAULT_EXPORT)
    ap.add_argument("--out", type=Path, default=Path("output"))
    args = ap.parse_args()

    df, s = clean(args.export)

    pd.set_option("display.max_rows", None, "display.max_columns", None,
                  "display.max_colwidth", 70, "display.width", 250)
    table_cols = ["review_id", "store", "review_date", "star_rating", "device_model", TEXT_COL]
    report = (
        f"Source file:          {args.export}\n"
        f"Starting rows:        {s['start']}\n"
        f"Blank removed:        {s['blank']}  (file lines {s['blank_rows']})\n"
        f"Duplicates removed:   {s['dup']}  (file lines {s['dup_rows']})\n"
        f"Kept rows:            {s['kept']}\n"
        f"Check:                {s['start']} - {s['blank']} - {s['dup']} = {s['kept']}\n\n"
        f"{df[table_cols].to_string(index=False)}\n"
    )
    assert s["start"] - s["blank"] - s["dup"] == s["kept"]
    assert df["review_id"].is_unique

    print(report)
    args.out.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out / "cleaned_reviews.csv", index=False)
    (args.out / "cleaned_reviews.txt").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
