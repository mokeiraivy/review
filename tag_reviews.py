""""
Stage 3: tag every cleaned review with the OpenAI model through a LangChain chain.

Run (from the repo root, after setting the two environment variables):
    PowerShell:  $env:OPENAI_API_KEY = "sk-..."
                 $env:OPENAI_MODEL   = "<model id>"
                 python tag_reviews.py
    bash:        OPENAI_API_KEY=sk-... OPENAI_MODEL=<model id> python tag_reviews.py

For OpenRouter (OpenAI-compatible), also set:
    $env:OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
and use an OpenRouter key and an OpenRouter model ID (e.g. "provider/model-name").

The model ID and API key are read ONLY from those environment variables. Neither
is written anywhere in the code or the saved output (the run log shows the model
ID, never the key).

Chain:  TAGGING_PROMPT  |  ChatOpenAI(model).with_structured_output(ReviewTag)
  - TAGGING_PROMPT and ReviewTag are the stage 2 rules, used unchanged.
  - review_id is attached in code, never asked from the model.

Quote check (character for character, no fuzzy matching):
  - product_flaw / feature_request: the quote must appear EXACTLY inside that
    review's own text (Python `quote in review_text`).
      pass      the model's quote matched exactly
      replaced  it did not match after MAX_ATTEMPTS tries, so it was swapped for a
                real sentence cut straight out of the same review (the sentence
                sharing the most words with the model's quote). The replacement is
                re-checked with the same exact test, and the model's original quote
                is kept in model_quote for the audit.
  - neither: theme and quote must be empty  ->  "empty (neither)".
  The log proves: passed + replaced = product_flaw rows + feature_request rows.

Outputs:
  output/tagged_reviews.csv   one row per review: the stage 1 table with the tag
                              column filled, plus theme, quote, quote_check,
                              model_quote, reason, attempts
  output/tagging_run.txt      a saved copy of everything printed to the terminal
"""

import os
import re
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
QUOTE_REPLACED = "replaced"
QUOTE_EMPTY_OK = "empty (neither)"
QUOTE_FAIL = "FAIL"


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


def base_url():
    """Optional OpenAI-compatible endpoint (e.g. OpenRouter). Read from env, never hard-coded."""
    return os.environ.get("OPENAI_BASE_URL", "").strip() or None


def build_chain(api_key, model):
    from langchain_openai import ChatOpenAI

    llm_kwargs = {"model": model, "api_key": api_key}
    if base_url():                                       # e.g. OpenRouter: https://openrouter.ai/api/v1
        llm_kwargs["base_url"] = base_url()
    if os.environ.get("OPENAI_TEMPERATURE"):           # optional, e.g. "0" for repeatable runs
        llm_kwargs["temperature"] = float(os.environ["OPENAI_TEMPERATURE"])
    llm = ChatOpenAI(**llm_kwargs)
    return TAGGING_PROMPT | llm.with_structured_output(
        ReviewTag, method="function_calling", include_raw=True
    )


def quote_matches(quote, review_text) -> bool:
    """The one quote test: exact, character for character. No normalising."""
    return bool(quote) and quote in review_text


def review_sentences(review_text):
    """Sentences cut straight out of the review text, so each one is an exact substring."""
    parts = (m.group().strip() for m in re.finditer(r"[^.!?]+[.!?]*", review_text))
    return [p for p in parts if re.search(r"[^\W_]", p) and p in review_text]


def replacement_sentence(model_quote, review_text):
    """Pick the real sentence that shares the most words with the model's quote
    (first sentence on a tie). This only CHOOSES which real sentence to use; the
    sentence itself is copied from the review unchanged."""
    words = set(re.findall(r"\w+", (model_quote or "").lower()))
    sentences = review_sentences(review_text)
    if not sentences:
        return None
    return max(sentences, key=lambda s: len(words & set(re.findall(r"\w+", s.lower()))))


def tag_one(chain, review_text):
    """Return (tag or None, model_quote, quote_check, attempts, note)."""
    tag, note = None, "no answer from the model"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            out = chain.invoke({"review_text": review_text})
        except Exception as e:                           # network / API error
            note = f"{type(e).__name__}: {e}"
            time.sleep(2 * attempt)
            continue
        if out.get("parsing_error") or out.get("parsed") is None:
            note = f"schema rejected the answer: {out.get('parsing_error')}"
            continue
        tag = out["parsed"]
        if tag.category == Category.NEITHER:             # schema already forces empty theme/quote
            return tag, "", QUOTE_EMPTY_OK, attempt, ""
        if quote_matches(tag.quote, review_text):
            return tag, tag.quote, QUOTE_PASS, attempt, ""
        note = "model quote not found character for character"

    if tag is None or tag.category == Category.NEITHER:
        return tag, "", QUOTE_FAIL, MAX_ATTEMPTS, note

    # Still no exact match after every attempt: swap in a real sentence.
    model_quote = tag.quote
    real = replacement_sentence(model_quote, review_text)
    if real and quote_matches(real, review_text):
        tag = tag.model_copy(update={"quote": real})
        return tag, model_quote, QUOTE_REPLACED, MAX_ATTEMPTS, note
    return tag, model_quote, QUOTE_FAIL, MAX_ATTEMPTS, note


def tag_all(chain, reviews: pd.DataFrame, log: Tee):
    rows, tags = [], []
    for i, r in enumerate(reviews.itertuples(index=False), start=1):
        tag, model_quote, qcheck, attempts, note = tag_one(chain, r.review_text)
        if tag is not None:
            tags.append(tag)
        rows.append({
            "review_id": r.review_id,
            "tag": tag.category.value if tag else "",
            "theme": (tag.theme or "") if tag else "",
            "quote": (tag.quote or "") if tag else "",
            "quote_check": qcheck,
            "model_quote": model_quote,
            "reason": tag.reason if tag else note,
            "attempts": attempts,
        })
        log(f"  [{i:>2}/{len(reviews)}] {r.review_id}  {rows[-1]['tag'] or 'UNLABELLED':<16} quote: {qcheck}")
        if tag is None:
            log(f"         error: {note[:300]}")
            if i == 1:
                log("         First review failed with no answer. Check the key, OPENAI_BASE_URL and model ID.")
    tagged = pd.DataFrame(rows)
    out = reviews.drop(columns=["tag"], errors="ignore").merge(tagged, on="review_id", how="left")
    return out, tags


def report(log: Tee, out: pd.DataFrame, tags):
    total = len(out)
    labelled = int((out["tag"] != "").sum())
    n = {c.value: int((out["tag"] == c.value).sum()) for c in Category}
    q = {k: int((out["quote_check"] == k).sum())
         for k in (QUOTE_PASS, QUOTE_REPLACED, QUOTE_EMPTY_OK, QUOTE_FAIL)}
    flaw_req = n["product_flaw"] + n["feature_request"]

    log("")
    log("TAGGED TABLE")
    pd.set_option("display.max_colwidth", 60, "display.width", 250, "display.max_rows", None)
    log(out[["review_id", "tag", "theme", "quote_check", "quote"]].to_string(index=False))

    log("")
    log("SUMMARY")
    log(f"  Labelled rows:              {labelled}/{total}")
    log(f"  product_flaw:               {n['product_flaw']}")
    log(f"  feature_request:            {n['feature_request']}")
    log(f"  neither:                    {n['neither']}")
    log("")
    log("  Quotes on flaw + request rows (must add up):")
    log(f"    passed (exact match):     {q[QUOTE_PASS]}")
    log(f"    replaced (real sentence): {q[QUOTE_REPLACED]}")
    log(f"    passed + replaced:        {q[QUOTE_PASS]} + {q[QUOTE_REPLACED]} = {q[QUOTE_PASS] + q[QUOTE_REPLACED]}")
    log(f"    flaw + request rows:      {n['product_flaw']} + {n['feature_request']} = {flaw_req}")
    adds_up = q[QUOTE_PASS] + q[QUOTE_REPLACED] == flaw_req
    log(f"    adds up:                  {'YES' if adds_up else 'NO'}")
    log(f"  Neither rows with empty theme and quote: {q[QUOTE_EMPTY_OK]} of {n['neither']}")
    log(f"  FAIL (no usable quote):     {q[QUOTE_FAIL]}")

    if q[QUOTE_REPLACED]:
        log("")
        log("REPLACED QUOTES (model's version kept in model_quote for the audit)")
        for r in out[out["quote_check"] == QUOTE_REPLACED].itertuples(index=False):
            log(f"  {r.review_id}")
            log(f"    model said: {r.model_quote!r}")
            log(f"    replaced by: {r.quote!r}")

    log("")
    log("MENTIONS PER THEME (severity: high >= 5, medium 2-4, low 1)")
    for r in theme_summary(tags):
        log(f"  {r['category']:<16} {r['theme']:<32} mentions={r['mentions']:<3} severity={r['severity']}")

    return labelled == total and adds_up and q[QUOTE_FAIL] == 0 and q[QUOTE_EMPTY_OK] == n["neither"]


def main():
    api_key, model = read_settings()
    reviews = pd.read_csv(CLEANED, dtype=str, keep_default_na=False)

    log = Tee()
    log("STAGE 3 - TAGGING RUN")
    log(f"Model:   {model}  (from OPENAI_MODEL; API key read from OPENAI_API_KEY, not shown)")
    log(f"Endpoint: {base_url() or 'OpenAI default'}  (from OPENAI_BASE_URL)")
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