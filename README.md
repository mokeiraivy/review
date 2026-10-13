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
| `tagging_prompt.py` | `TAGGING_PROMPT`: a LangChain `PromptTemplate` built from the fixed instruction text. Every rule is pre-filled from the schema, so its only input is `review_text`. The chain uses it as `TAGGING_PROMPT \| llm.with_structured_output(ReviewTag)`. |
| `tagging_schema.py` | The output schema (Pydantic), the severity thresholds as named constants, and `theme_summary()`, which counts mentions per theme. |
| `check_tagging_rules.py` | Checks the rules without calling a model and saves `output/tagging_rules_check.txt`. |

## Categories (each defined in the prompt with a real review from the export)

| Category | Example review | Why it's tricky |
|---|---|---|
| `product_flaw` | `rv_36484054c9`: "there's no way to tell which fonts and graphics are Pro until you try to save…" | Ends with a suggestion ("put a crown on them"), but the problem is that the editor hides Pro items until save. |
| `feature_request` | `rv_e209f393ab`: "…I can't find my brand kit anywhere… Please add brand kit to mobile" | "Can't find" sounds like a bug, but brand kit isn't in the mobile editor. |
| `neither` | `rv_5e547992d8`: "Really like the new editor… Only wish the background remover was on the free plan…" | Praise plus a pricing wish. Nothing is broken and nothing needs building. |

## Output schema: one tag per review

`ReviewTag` has exactly four fields, which the model fills in: `category`, `theme`, `quote`, `reason`.
`review_id` is attached in code. The model never gives a severity or a score, and the schema rejects them.

- **One winner.** If a review raises more than one issue, the category that comes first in
  `CATEGORY_PRIORITY` wins (product_flaw, then feature_request, then neither). Within that
  category, the issue the review mentions first wins.
- **Neither keeps theme and quote empty.** The model must not copy or invent a sentence
  for a neither review, and the schema rejects one if it does.

## Severity: from mention counts, in code

On the dashboard card, the number next to the severity is the **mention count**: how many
reviews raised that theme this week. So severity is worked out per theme in code, never
per review and never by the model.

| Constant (`tagging_schema.py`) | Value | Severity |
|---|---|---|
| `HIGH_MIN_MENTIONS` | 5 | 5 or more mentions → high |
| `MEDIUM_MIN_MENTIONS` | 2 | 2–4 mentions → medium |
| `LOW_MIN_MENTIONS` | 1 | 1 mention → low |

`theme_summary(tags)` counts tags per (category, theme) and applies `severity_label()`.
A crash six users hit is high, and a crash one user hit is low.

## Rules written once

`WINNER_RULE`, `THEME_RULE`, `QUOTE_RULE` and `NEITHER_QUOTE_RULE` are defined only in
`tagging_schema.py`. The prompt and the field descriptions read them from there.

## Check

```bash
python check_tagging_rules.py
```

Expected: `33/33 checks passed`. It also saves `output/tagging_rules_check.txt`
with the thresholds and a worked severity example, the category examples, the
schema fields, every check result, and the full prompt filled with a real review
(`rv_cdf86c6e0b`), so a reviewer can read it without running anything.

---

# Stage 3: Tagging chain (LangChain + OpenAI)

`tag_reviews.py` sends every cleaned review to the OpenAI model and reads back one
`ReviewTag` per review:

```
TAGGING_PROMPT | ChatOpenAI(model).with_structured_output(ReviewTag)
```

The prompt and schema are the stage 2 rules, unchanged. `review_id` is attached in code.

## Run

The model ID and API key come **only** from environment variables. They are never
written in the code, and the run log shows the model ID but never the key.

```powershell
pip install -r requirements.txt
$env:OPENAI_API_KEY = "sk-..."
$env:OPENAI_MODEL   = "<model id>"
python tag_reviews.py
```

Optional: `$env:OPENAI_TEMPERATURE = "0"` for repeatable runs, on models that support it.

## Quote check: character for character

- **product_flaw / feature_request:** the quote must appear exactly inside that review's
  own text (`quote in review_text`), with no normalising and no fuzzy matching.
  - `pass`: the model's quote matched exactly.
  - `replaced`: it still didn't match after `MAX_ATTEMPTS = 3` tries, so it was swapped for
    a real sentence cut straight out of the same review (the one sharing the most words with
    the model's quote). The replacement passes the same exact test, and the model's original
    is kept in `model_quote` for the audit.
- **neither:** theme and quote stay empty (`empty (neither)`).

The run log prints the tagged table and states the two numbers that must add up:
**passed + replaced = product_flaw rows + feature_request rows**, even when replaced is 0.
The script exits non-zero if any row is unlabelled, the numbers don't add up, or a quote fails.

## Outputs

- `output/tagged_reviews.csv`: one row per review, with the stage 1 table, the `tag` column
  filled, and `theme`, `quote`, `quote_check`, `model_quote`, `reason` and `attempts`.
- `output/tagging_run.txt`: a saved copy of the terminal output. It shows every review's label,
  the full tagged table, labelled rows out of the total, counts per category, passed + replaced
  against flaw + request rows, any replaced quotes side by side, and mentions per theme with severity.