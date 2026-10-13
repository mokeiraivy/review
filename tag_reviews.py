"""
Stage 3: tag every cleaned review with the OpenAI model through a LangChain chain.

Run (from the repo root, after setting the two environment variables):
    PowerShell:  $env:OPENAI_API_KEY = "sk-..."
                 $env:OPENAI_MODEL   = "<model id>"
                 python tag_reviews.py
    bash:        OPENAI_API_KEY=sk-... OPENAI_MODEL=<model id> python tag_reviews.py

The model ID and API key are read ONLY from those environment variables. Neither
is written anywhere in the code or the saved output (the run log shows the model
ID, never the key).

Chain:  TAGGING_PROMPT  |  ChatOpenAI(model).with_structured_output(ReviewTag)
  - TAGGING_PROMPT and ReviewTag are the stage 2 rules, used unchanged.
  - review_id is attached in code, never asked from the model.

Quote check (character for character, no fuzzy matching):
  - product_flaw / feature_request: the quote must appear EXACTLY inside that
    review's own text (Python `quote in review_text`). Anything else is FAIL.
  - neither: theme and quote must be empty. An invented one is FAIL.
  A failed review is retried; if it still fails, the row is kept with
  quote_check = FAIL so the audit step can see it, and the script exits non-zero.

Outputs:
  output/tagged_reviews.csv   one row per review: the stage 1 table with the tag
                              column filled, plus theme, quote, quote_check, reason
  output/tagging_run.txt      a saved copy of everything printed to the terminal
"""

import os
import sys
import time
from pathlib import Path

import pandas as pd

from tagging_prompt import TAGGING_PROMPT
from tagging_schema import Category, ReviewTag, theme_summary

CLEANED = Path("output/cleaned_reviews.csv")
TAGS_OUT = Path("output/tagged_reviews.csv")
RUN_LOG = Path("output/tagging_run.txt")
MAX_ATTEMPTS = 3

QUOTE_PASS = "pass"
QUOTE_EMPTY_OK = "empty (neither)"


class Tee:
    """Print to the terminal and keep a copy for the saved run log."""

    def __init__(self):
        self.lines = []

    def __call__(self, line=""):
        print(line, flush=True)
        self.lines.append(line)

    def save(self, path):
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def read_settings():
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip()
    missing = [name for name, val in (("OPENAI_API_KEY", api_key), ("OPENAI_MODEL", model)) if not val]
    if missing:
        sys.exit(f"Missing environment variable(s): {', '.join(missing)}. "
                 "Set them before running; they are never written in the code.")
    return api_key, model


def build_chain(api_key, model):
    from langchain_openai import ChatOpenAI

    llm_kwargs = {"model": model, "api_key": api_key}
    if os.environ.get("OPENAI_TEMPERATURE"):           # optional, e.g. "0" for repeatable runs
        llm_kwargs["temperature"] = float(os.environ["OPENAI_TEMPERATURE"])
    llm = ChatOpenAI(**llm_kwargs)
    return TAGGING_PROMPT | llm.with_structured_output(
        ReviewTag, method="function_calling", include_raw=True
    )


def check_quote(tag: ReviewTag, review_text: str) -> str:
    """Character-for-character check. No normalising, no fuzzy matching."""
    if tag.category == Category.NEITHER:
        if tag.theme is None and tag.quote is None:
            return QUOTE_EMPTY_OK
        return "FAIL: neither must keep theme and quote empty"
    if tag.quote and tag.quote in review_text:
        return QUOTE_PASS
    return "FAIL: quote not found character for character in the review"


def tag_one(chain, review_text):
    """Return (tag or None, quote_check, attempts, last_error)."""
    last_error, tag, result = "", None, "FAIL: no answer from the model"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            out = chain.invoke({"review_text": review_text})
        except Exception as e:                           # network / API error
            last_error = f"{type(e).__name__}: {e}"
            time.sleep(2 * attempt)
            continue
        if out.get("parsing_error") or out.get("parsed") is None:
            last_error = f"schema rejected the answer: {out.get('parsing_error')}"
            continue
        tag = out["parsed"]
        result = check_quote(tag, review_text)
        if result in (QUOTE_PASS, QUOTE_EMPTY_OK):
            return tag, result, attempt, ""
        last_error = result
    return tag, result, MAX_ATTEMPTS, last_error


def tag_all(chain, reviews: pd.DataFrame, log: Tee):
    rows = []
    for i, r in enumerate(reviews.itertuples(index=False), start=1):
        tag, qcheck, attempts, err = tag_one(chain, r.review_text)
        rows.append({
            "review_id": r.review_id,
            "tag": tag.category.value if tag else "",
            "theme": (tag.theme or "") if tag else "",
            "quote": (tag.quote or "") if tag else "",
            "quote_check": qcheck,
            "reason": tag.reason if tag else err,
            "attempts": attempts,
        })
        label = rows[-1]["tag"] or "UNLABELLED"
        log(f"  [{i:>2}/{len(reviews)}] {r.review_id}  {label:<16} {rows[-1]['theme'][:28]:<28} quote: {qcheck}")
    tagged = pd.DataFrame(rows)
    out = reviews.drop(columns=["tag"], errors="ignore").merge(tagged, on="review_id", how="left")
    return out, [t for t in (_row_to_tag(r) for r in rows) if t is not None]


def _row_to_tag(row):
    if not row["tag"]:
        return None
    return ReviewTag(category=row["tag"], theme=row["theme"] or None,
                     quote=row["quote"] or None, reason=row["reason"] or "-")


def report(log: Tee, out: pd.DataFrame, tags):
    total = len(out)
    labelled = int((out["tag"] != "").sum())
    log("")
    log("SUMMARY")
    log(f"  Labelled rows:        {labelled}/{total}")
    for cat in Category:
        log(f"  {cat.value:<21} {int((out['tag'] == cat.value).sum())}")
    passed = int((out["quote_check"] == QUOTE_PASS).sum())
    empty_ok = int((out["quote_check"] == QUOTE_EMPTY_OK).sum())
    failed = int(out["quote_check"].str.startswith("FAIL").sum())
    log(f"  Quote check:          {passed} exact match, {empty_ok} empty (neither), {failed} FAIL")
    log(f"  Check:                {passed} + {empty_ok} + {failed} = {passed + empty_ok + failed} of {total}")
    log("")
    log("MENTIONS PER THEME (severity: high >= 5, medium 2-4, low 1)")
    for r in theme_summary(tags):
        log(f"  {r['category']:<16} {r['theme']:<32} mentions={r['mentions']:<3} severity={r['severity']}")
    if failed:
        log("")
        log("FAILED QUOTE CHECKS (kept for the audit, not trusted):")
        for r in out[out["quote_check"].str.startswith("FAIL")].itertuples(index=False):
            log(f"  {r.review_id}: {r.quote_check} | model quote: {r.quote!r}")
    return labelled == total and failed == 0


def main():
    api_key, model = read_settings()
    reviews = pd.read_csv(CLEANED, dtype=str, keep_default_na=False)

    log = Tee()
    log("STAGE 3 - TAGGING RUN")
    log(f"Model:   {model}  (from OPENAI_MODEL; API key read from OPENAI_API_KEY, not shown)")
    log(f"Input:   {CLEANED}  ({len(reviews)} reviews, review_text column)")
    log("")
    chain = build_chain(api_key, model)
    out, tags = tag_all(chain, reviews, log)
    ok = report(log, out, tags)

    TAGS_OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(TAGS_OUT, index=False)
    log("")
    log(f"Saved tag table to {TAGS_OUT}")
    log(f"Saved this output to {RUN_LOG}")
    log.save(RUN_LOG)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()