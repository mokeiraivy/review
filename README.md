# Weekly Review Digest — Stage 1: Clean reviews

Cleans this week's Canva mobile editor reviews (App Store + Google Play) into a
pandas table, one review per row. Every later stage counts and quotes these rows.

## Run

```bash
pip install -r requirements.txt
python clean_reviews.py
```

The script reads `data/Canva_Mobile_Editor_Review_Export_2-8_June_2025.csv`
(nothing is typed in by hand), prints the starting and kept row counts and the
cleaned table, and saves:

- `output/cleaned_reviews.txt` — the printed table and counts
- `output/cleaned_reviews.csv` — the cleaned table for later stages

For another week: `python clean_reviews.py path/to/export.csv`

## Result for 2–8 June 2025

| | Rows |
|---|---|
| Starting rows | 22 |
| Blank removed | 2 (file lines 9, 15) |
| Duplicates removed | 2 (file lines 8, 20) |
| **Kept rows** | **18** |

## Rules

**Blank review.** `review_text` is missing, or contains no letter or digit once
whitespace is ignored (`""`, `"    "`, `"..."`, `"😡"`). It has nothing to count or
quote, so it is dropped. A missing `review_title` alone does not make a row blank.

**Duplicate review.** Every column (store, review_date, star_rating, app_version,
device_model, platform_os, review_title, review_text) matches an earlier row,
comparing text after trimming, lower-casing and collapsing whitespace. The first
occurrence is kept. This catches the same review exported twice, without merging
different users who happen to write similar words, since each of them is a real mention.

**Stable ID.** `review_id = "rv_" + first 10 hex chars of SHA-1(normalised columns)`.
It comes from the review's own content, not its row position, so it is the same on
every run, even if rows are reordered or new ones are added.

**Tag column.** Every kept row gets an empty `tag` column. The next stage (LLM
tagging) writes each review's theme into it, and counts are made from those tags.
The printout shows `review_id`, `store`, `review_date`, `review_text` and `tag`,
so a reviewer can check each row from the printout alone. The CSV keeps every column.

`review_text` is kept exactly as in the export (only leading and trailing spaces
are trimmed) so later quote checks can match it word for word.

---

# Stage 2: Tagging rules (prompt template + output schema)

The rules the language model follows when it reads each review. The tagging
chain in the next stage runs on exactly these files.

| File | What it is |
|---|---|
| `tagging_prompt.py` | `PROMPT_TEMPLATE`: the fixed instruction, with one slot `{review_text}`. `build_prompt()` fills it. |
| `tagging_schema.py` | The output schema (Pydantic) and the severity thresholds as named constants. |
| `check_tagging_rules.py` | Checks the rules without calling a model. |

## Categories (each defined in the prompt with a real review from the export)

| Category | Example review | Why it's tricky |
|---|---|---|
| `product_flaw` | `rv_36484054c9`: "there's no way to tell which fonts and graphics are Pro until you try to save…" | Ends with a suggestion ("put a crown on them"), but the problem is that the editor hides Pro items until save. |
| `feature_request` | `rv_e209f393ab`: "…I can't find my brand kit anywhere… Please add brand kit to mobile" | "Can't find" sounds like a bug, but brand kit isn't in the mobile editor. |
| `neither` | `rv_5e547992d8`: "Really like the new editor… Only wish the background remover was on the free plan…" | Praise plus a pricing wish. Nothing is broken and nothing needs building. |

## Output schema (what the model fills in, per finding)

`category`, `theme`, `impact_score`, `quote` (one sentence copied exactly), and `reason`.
A review can have several findings. `neither` must be the only finding when it is used.
`review_id` is attached in code, not by the model.

## Severity thresholds (in `tagging_schema.py`, never in the prompt text)

The model gives an `impact_score` from `IMPACT_SCORE_MIN` to `IMPACT_SCORE_MAX`.
Code turns it into a label:

| Constant | Value | Label |
|---|---|---|
| `CRITICAL_THRESHOLD` | 9 | score ≥ 9 → critical |
| `HIGH_THRESHOLD` | 7 | 7–8 → high |
| `MEDIUM_THRESHOLD` | 4 | 4–6 → medium, below 4 → low |

The prompt text contains no digits. `build_prompt()` inserts the scale numbers
from these constants, so changing a threshold in code updates the prompt too.

## Check

```bash
python check_tagging_rules.py
```

Expected: `17/17 checks passed`.