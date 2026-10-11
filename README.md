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