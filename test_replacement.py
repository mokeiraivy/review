"""
Offline test of the quote-replacement branch in tag_reviews.py.

The real run came back with replaced = 0, so the swap code never fired against
model output. This test forces it: a fake model returns a reworded quote for one
review every time, and the test checks that the row is marked "replaced", gets
the review's first full sentence word for word, and keeps the model's version in
model_quote. No API key or network needed.

Run:  python test_replacement.py
"""

import sys

import pandas as pd

import tag_reviews as T
from tagging_schema import ReviewTag

T.time.sleep = lambda s: None          # no real waiting in the test
if hasattr(T, "REQUEST_DELAY"):
    T.REQUEST_DELAY = 0                # skip the pause between reviews

TARGET = "rv_aba4ca6b7b"
# Reworded version of the review's SECOND sentence ("Tried with wifi and data, cleared
# cache, nothing works."). A word-overlap rule would pick that second sentence; the
# first-sentence rule must pick sentence one. So this test fails on the old rule.
REWORDED = "Tried with wifi and mobile data, cleared the cache, nothing works."


class FakeChain:
    def __init__(self, reviews):
        self.text_to_id = dict(zip(reviews.review_text, reviews.review_id))

    def invoke(self, d):
        text = d["review_text"]
        first = T.review_sentences(text)[0]
        quote = REWORDED if self.text_to_id[text] == TARGET else first
        tag = ReviewTag(category="product_flaw", theme="test theme", quote=quote, reason="test")
        return {"raw": None, "parsed": tag, "parsing_error": None}


reviews = pd.read_csv(T.CLEANED, dtype=str, keep_default_na=False)
log = T.Tee()
out, tags = T.tag_all(FakeChain(reviews), reviews, lambda *a: None)
row = out.set_index("review_id").loc[TARGET]
text = reviews.set_index("review_id").loc[TARGET, "review_text"]
sentences = T.review_sentences(text)
expected = sentences[0]

results = [
    ("reworded quote is marked replaced", row.quote_check == T.QUOTE_REPLACED),
    ("replacement is the review's first full sentence", row.quote == expected),
    ("replacement is NOT the sentence the reworded quote resembles (old word-overlap rule)",
     row.quote != sentences[1]),
    ("replacement appears character for character in the review", row.quote in text),
    ("model's original quote is kept in model_quote", row.model_quote == REWORDED),
    ("it took MAX_ATTEMPTS tries before replacing", int(row.attempts) == T.MAX_ATTEMPTS),
    ("every other row passed", (out.drop(out[out.review_id == TARGET].index).quote_check == T.QUOTE_PASS).all()),
]
for name, ok in results:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
print(f"\n  model said:   {REWORDED!r}")
print(f"  replaced by:  {row.quote!r}")
print(f"\n{sum(ok for _, ok in results)}/{len(results)} checks passed")
sys.exit(0 if all(ok for _, ok in results) else 1)