"""
Checks the stage 2 tagging rules without calling any model.

Run:  python check_tagging_rules.py

1. Each category example in the prompt is a real review, word for word.
2. The prompt template text contains no digits, so no thresholds are buried in it.
3. The severity thresholds are named integer constants, in order, in code.
4. build_prompt() fills every slot and puts the review text in.
5. The schema accepts valid output and rejects invalid output.
"""

import re
import sys

import pandas as pd
from pydantic import ValidationError

import tagging_schema as S
from tagging_prompt import EXAMPLE_REVIEW_IDS, PROMPT_TEMPLATE, build_prompt

CLEANED = "output/cleaned_reviews.csv"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))


reviews = pd.read_csv(CLEANED, dtype=str).set_index("review_id")["review_text"]

# 1. Examples are real reviews, copied exactly
for category, rid in EXAMPLE_REVIEW_IDS.items():
    text = reviews.get(rid)
    check(f"{category} example {rid} is in the export and appears verbatim in the prompt",
          text is not None and text in PROMPT_TEMPLATE)

# 2. No numbers written into the template text
digits = re.findall(r"\d", PROMPT_TEMPLATE)
check("prompt template has no hard-coded numbers", not digits,
      f"found {digits}" if digits else "scale numbers are filled in from tagging_schema")

# 3. Thresholds are named constants in code
names = ["MEDIUM_THRESHOLD", "HIGH_THRESHOLD", "CRITICAL_THRESHOLD"]
values = [getattr(S, n) for n in names]
check("three severity thresholds are named int constants in tagging_schema.py",
      all(isinstance(v, int) for v in values),
      ", ".join(f"{n}={v}" for n, v in zip(names, values)))
check("thresholds are in order inside the score scale",
      S.IMPACT_SCORE_MIN < S.MEDIUM_THRESHOLD < S.HIGH_THRESHOLD < S.CRITICAL_THRESHOLD <= S.IMPACT_SCORE_MAX)
mapping = {s: S.severity_label(s).value for s in range(S.IMPACT_SCORE_MIN, S.IMPACT_SCORE_MAX + 1)}
print("       score -> severity:", mapping)

# 4. Prompt renders for a real review
sample_id = "rv_cdf86c6e0b"
rendered = build_prompt(reviews[sample_id])
check("build_prompt fills every slot", "{" not in rendered and "}" not in rendered)
check("rendered prompt contains the review text exactly", reviews[sample_id] in rendered)
check("rendered prompt shows the threshold values from code",
      all(str(v) in rendered for v in values))

# 5. Schema accepts valid output and rejects invalid output
sentence = "PDF export fails at the very end and the whole app is laggy when I drag text around."
valid = {
    "findings": [
        {"category": "product_flaw", "theme": "pdf export fails", "impact_score": 9,
         "quote": sentence, "reason": "Export never finishes, so the user cannot get their file."},
        {"category": "product_flaw", "theme": "text box lag", "impact_score": 5,
         "quote": sentence, "reason": "Dragging text lags but still works."},
    ]
}
try:
    parsed = S.ReviewTagging.model_validate(valid)
    check("schema accepts a review with two findings", True,
          f"primary = {parsed.primary.theme} ({parsed.primary.severity.value})")
    check("every quote in the valid sample is a real sentence of that review",
          all(f.quote in reviews[sample_id] for f in parsed.findings))
except ValidationError as e:
    check("schema accepts a review with two findings", False, str(e))

bad_cases = {
    "neither with an impact score": {"findings": [
        {"category": "neither", "impact_score": 3, "quote": "x", "reason": "x"}]},
    "flaw without an impact score": {"findings": [
        {"category": "product_flaw", "theme": "crash", "quote": "x", "reason": "x"}]},
    "score above the scale": {"findings": [
        {"category": "product_flaw", "theme": "crash", "impact_score": S.IMPACT_SCORE_MAX + 1,
         "quote": "x", "reason": "x"}]},
    "neither mixed with a flaw": {"findings": [
        {"category": "neither", "quote": "x", "reason": "x"},
        {"category": "product_flaw", "theme": "crash", "impact_score": 5, "quote": "x", "reason": "x"}]},
    "unknown category": {"findings": [
        {"category": "bug", "theme": "crash", "impact_score": 5, "quote": "x", "reason": "x"}]},
    "no findings": {"findings": []},
}
for name, data in bad_cases.items():
    try:
        S.ReviewTagging.model_validate(data)
        check(f"schema rejects: {name}", False, "was accepted")
    except ValidationError:
        check(f"schema rejects: {name}", True)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)