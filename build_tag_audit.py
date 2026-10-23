"""
Stage 4: tagging audit table, one row per review.

Run:  python build_tag_audit.py

Reads
  audit/tagged_reviews_before.csv   the chain's output BEFORE the fix (saved copy of
                                    the stage 3 run, because the rerun overwrites output/)
  output/tagged_reviews.csv         the chain's output AFTER the fix (the rerun), if present
Writes
  audit/tag_audit.csv               the audit table, one row per review
  audit/tag_audit.txt               the same table printed, plus findings and
                                    mention counts before vs after

The "before" columns are read from the chain's real output, never typed in.
The judgement columns (label_fits, theme_judgement, label_after, theme_after,
change, finding) are the audit: one entry per review in AUDIT below. The script
refuses to run if any review is missing a judgement or has a blank change.
"""

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from tagging_schema import severity_label

BEFORE = Path("audit/tagged_reviews_before.csv")
AFTER = Path("output/tagged_reviews.csv")
AUDIT_CSV = Path("audit/tag_audit.csv")
AUDIT_TXT = Path("audit/tag_audit.txt")

NO_CHANGE = "no change"

# ---------------------------------------------------------------------------
# Findings: each one names the rows that show it and the chain change that fixes it.
# ---------------------------------------------------------------------------
FINDINGS = {
    "F1": ("Same problem, two labels: MP4 export stuck at 99%",
           "rv_aba4ca6b7b got 'mp4 export stuck at 99%' and rv_4e1bf0fa7c got 'mp4 export stalls'. "
           "Both reviews say MP4 export stops at 99% and never finishes. Split, each counts 1 (low); "
           "together they are 2 (medium).",
           "Fixed theme catalogue in tagging_schema.py: one entry 'mp4 export stuck at 99%'."),
    "F2": ("Same problem, two labels: Pro shown only at download",
           "rv_6866864537 got 'background remover not marked pro' while three other reviews with the "
           "same problem (Pro revealed only at save/download) got 'pro items not marked'. The count "
           "shows 3 + 1 instead of 4.",
           "Fixed theme catalogue: one entry 'pro items not marked', defined to cover any element, "
           "font or tool the user only learns is Pro at save or download."),
    "F3": ("Same problem, three labels: app crashes",
           "rv_e5da5d4c58 'crash on template tap', rv_0adbf47db0 'app closes when adding photos' and "
           "rv_49906f6ab7 'freezes and crashes on text-heavy designs' all describe the app closing "
           "itself. The labels name the trigger instead of the problem, so each counts 1 (low); "
           "together they are 3 (medium).",
           "Fixed theme catalogue: one entry 'app crashes', defined as the app closing itself "
           "whatever triggered it."),
    "F4": ("Request theme worded as a fault",
           "rv_b4b6fd5646 is correctly a feature_request, but its theme 'keyboard shortcuts not "
           "working' reads like a bug, which contradicts the label on the dashboard card.",
           "Fixed theme catalogue: request themes are named as the wish "
           "('keyboard shortcuts on ipad'), and the schema rejects a theme from the wrong category."),
}
ROOT_CAUSE = (
    "Root cause of F1-F3: the chain tags each review in a separate call, so the model never "
    "sees the themes it gave earlier reviews. The old rule 'use the same wording every time' "
    "could not be followed. The fix replaces free-text themes with a fixed catalogue the "
    "model must pick from."
)
CONSIDERED_NOT_CHANGED = [
    "PDF export failing (rv_b1f196379e, rv_cdf86c6e0b) was NOT merged with MP4 stuck at 99%: "
    "different export format, likely a different fault, so they stay separate themes.",
    "Slow PDF export (second issue in rv_b8f9550896) was NOT merged into 'pdf export fails': "
    "slow still finishes. It is not counted this week because the one-winner rule picks that "
    "review's Pro complaint.",
    "Text lag in rv_cdf86c6e0b (second issue) is not counted: the one-winner rule picks the "
    "PDF export failure, which the review mentions first. No change.",
]

# ---------------------------------------------------------------------------
# The audit: one judgement per review.
# (label_fits, label_after, theme_judgement, theme_after, change, finding)
# ---------------------------------------------------------------------------
TIGHT = "tight and specific"
AUDIT = {
    "rv_cbe4c75fba": ("yes", "product_flaw", TIGHT, "text box lag", NO_CHANGE, ""),
    "rv_e5da5d4c58": ("yes", "product_flaw", "too narrow: names the trigger, splits the crash count",
                      "app crashes", "theme merged into 'app crashes'", "F3"),
    "rv_b4b6fd5646": ("yes", "feature_request", "worded as a fault, contradicts the request label",
                      "keyboard shortcuts on ipad", "theme renamed as the wish", "F4"),
    "rv_b1f196379e": ("yes", "product_flaw", TIGHT, "pdf export fails", NO_CHANGE, ""),
    "rv_2626e4c6db": ("yes", "feature_request", TIGHT, "layers panel on mobile", NO_CHANGE, ""),
    "rv_e1e73fa600": ("yes", "product_flaw", TIGHT, "pro items not marked", NO_CHANGE, ""),
    "rv_aba4ca6b7b": ("yes", "product_flaw", TIGHT, "mp4 export stuck at 99%", NO_CHANGE, ""),
    "rv_0adbf47db0": ("yes", "product_flaw", "too narrow: names the trigger, splits the crash count",
                      "app crashes", "theme merged into 'app crashes'", "F3"),
    "rv_e209f393ab": ("yes", "feature_request", TIGHT, "brand kit on mobile", NO_CHANGE, ""),
    "rv_76433a6ce6": ("yes", "product_flaw", TIGHT, "text box lag", NO_CHANGE, ""),
    "rv_36484054c9": ("yes", "product_flaw", TIGHT, "pro items not marked", NO_CHANGE, ""),
    "rv_cdf86c6e0b": ("yes", "product_flaw", TIGHT, "pdf export fails", NO_CHANGE, ""),
    "rv_49906f6ab7": ("yes", "product_flaw", "too narrow: names the trigger, splits the crash count",
                      "app crashes", "theme merged into 'app crashes'", "F3"),
    "rv_742b5bf9a0": ("yes", "product_flaw", TIGHT, "text box lag", NO_CHANGE, ""),
    "rv_5e547992d8": ("yes", "neither", "n/a: neither keeps theme empty (correct)", "", NO_CHANGE, ""),
    "rv_b8f9550896": ("yes", "product_flaw", TIGHT, "pro items not marked", NO_CHANGE, ""),
    "rv_4e1bf0fa7c": ("yes", "product_flaw", "duplicate wording of 'mp4 export stuck at 99%'",
                      "mp4 export stuck at 99%", "theme merged into 'mp4 export stuck at 99%'", "F1"),
    "rv_6866864537": ("yes", "product_flaw", "duplicate: same Pro-at-download problem as 'pro items not marked'",
                      "pro items not marked", "theme merged into 'pro items not marked'", "F2"),
}
COLUMNS = ["label_fits", "label_after", "theme_judgement", "theme_after", "change", "finding"]


def counts(df, label_col, theme_col):
    c = Counter((r[label_col], r[theme_col]) for _, r in df.iterrows() if r[label_col] != "neither")
    return {k: v for k, v in c.items()}


def main():
    before = pd.read_csv(BEFORE, dtype=str, keep_default_na=False)
    ids = list(before["review_id"])

    missing = [i for i in ids if i not in AUDIT]
    extra = [i for i in AUDIT if i not in ids]
    if missing or extra:
        sys.exit(f"Audit does not cover the export exactly. Missing: {missing}  Extra: {extra}")

    table = before[["review_id", "review_text", "tag", "theme", "quote_check"]].rename(
        columns={"tag": "label_before", "theme": "theme_before"})
    for col_i, col in enumerate(COLUMNS):
        table[col] = [AUDIT[i][col_i] for i in table["review_id"]]

    blanks = table[(table["change"].str.strip() == "") | (table["label_fits"].isin(["yes", "no"]) == False)]
    if len(blanks):
        sys.exit(f"Rows with a blank change or missing yes/no: {list(blanks.review_id)}")

    # Rerun columns: what the fixed chain actually produced, and whether it matches the audit.
    has_rerun = AFTER.exists()
    if has_rerun:
        after = pd.read_csv(AFTER, dtype=str, keep_default_na=False).set_index("review_id")
        table["rerun_label"] = [after.loc[i, "tag"] if i in after.index else "MISSING" for i in table.review_id]
        table["rerun_theme"] = [after.loc[i, "theme"] if i in after.index else "MISSING" for i in table.review_id]
        table["rerun_matches_audit"] = [
            "yes" if (r.rerun_label == r.label_after and r.rerun_theme == r.theme_after) else "no"
            for r in table.itertuples()]

    order = ["review_id", "label_before", "label_fits", "label_after",
             "theme_before", "theme_judgement", "theme_after", "quote_check",
             "change", "finding"] + (["rerun_label", "rerun_theme", "rerun_matches_audit"] if has_rerun else []) \
        + ["review_text"]
    table = table[order]
    AUDIT_CSV.parent.mkdir(exist_ok=True)
    table.to_csv(AUDIT_CSV, index=False)

    # ----- printed report -----
    lines = []
    out = lines.append
    out("STAGE 4 - TAGGING AUDIT")
    out(f"Source (before): {BEFORE}   Rerun (after): {AFTER if has_rerun else 'not found'}")
    out("")
    out(f"Reviews in export:   {len(ids)}")
    out(f"Rows in audit:       {len(table)}  (every review covered: {'YES' if len(table) == len(ids) else 'NO'})")
    out(f"Label fits = yes:    {int((table.label_fits == 'yes').sum())}   no: {int((table.label_fits == 'no').sum())}")
    out(f"Rows changed:        {int((table.change != NO_CHANGE).sum())}   no change: {int((table.change == NO_CHANGE).sum())}")
    out(f"Blank change cells:  {int((table.change.str.strip() == '').sum())}")
    if has_rerun:
        out(f"Rerun matches audit: {int((table.rerun_matches_audit == 'yes').sum())}/{len(table)}")
    out("")
    pd.set_option("display.max_colwidth", 48, "display.width", 300, "display.max_rows", None)
    show = ["review_id", "label_before", "label_fits", "theme_before", "theme_judgement",
            "theme_after", "change", "finding"] + (["rerun_theme", "rerun_matches_audit"] if has_rerun else [])
    out(table[show].to_string(index=False))
    out("")
    out("FINDINGS (each traced to rows above and to a change in the chain)")
    for fid, (title, detail, fix) in FINDINGS.items():
        rows = list(table[table.finding == fid].review_id)
        out(f"  {fid}  {title}")
        out(f"      rows changed: {', '.join(rows)}")
        out(f"      found: {detail}")
        out(f"      fix:   {fix}")
    out(f"  {ROOT_CAUSE}")
    out("")
    out("CONSIDERED, NOT CHANGED")
    for n in CONSIDERED_NOT_CHANGED:
        out(f"  - {n}")
    out("")
    out("MENTIONS PER THEME (severity: high >= 5, medium 2-4, low 1)")
    b = counts(table, "label_before", "theme_before")
    a = counts(table, "label_after", "theme_after")
    out("  before (chain output):")
    for (cat, th), n in sorted(b.items(), key=lambda x: (x[0][0], -x[1])):
        out(f"    {cat:<16} {th:<42} {n}  {severity_label(n).value}")
    out("  after (audited):")
    for (cat, th), n in sorted(a.items(), key=lambda x: (x[0][0], -x[1])):
        out(f"    {cat:<16} {th:<42} {n}  {severity_label(n).value}")
    if has_rerun:
        r = counts(table, "rerun_label", "rerun_theme")
        out("  rerun (fixed chain):")
        for (cat, th), n in sorted(r.items(), key=lambda x: (x[0][0], -x[1])):
            out(f"    {cat:<16} {th:<42} {n}  {severity_label(n).value}")
    out("")
    out(f"Saved audit table to {AUDIT_CSV}")

    text = "\n".join(lines) + "\n"
    print(text, end="")
    AUDIT_TXT.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()