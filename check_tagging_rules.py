"""
Checks the stage 2 tagging rules without calling any model.

Run:  python check_tagging_rules.py

1. Each category example in the prompt is a real review, word for word.
2. The prompt template text contains no digits, so no thresholds are buried in it.
3. The severity thresholds are named integer constants, in order, in code.
4. Every rule that code enforces is written once, in tagging_schema.py, and the
   prompt and field descriptions read it from there.
5. TAGGING_PROMPT is a LangChain PromptTemplate with review_text as its only
   input, and the chain-style invoke gives the same text build_prompt() shows.
6. The schema accepts exactly one winning tag per review and rejects invalid output.
"""

import re
import sys

import pandas as pd
from pydantic import ValidationError

import tagging_schema as S
from langchain_core.prompts import PromptTemplate

from tagging_prompt import EXAMPLE_REVIEW_IDS, PROMPT_TEMPLATE, TAGGING_PROMPT, build_prompt

CLEANED = "output/cleaned_reviews.csv"
REPORT = "output/tagging_rules_check.txt"
results = []
check_lines = []


def check(name, ok, detail=""):
    results.append(ok)
    line = f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else "")
    check_lines.append(line)
    print(line)


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
check_lines.append(f"       score -> severity: {mapping}")
print("       score -> severity:", mapping)

# 4. Rules written once, in the schema
sample_id = "rv_cdf86c6e0b"
rendered = build_prompt(reviews[sample_id])
rules = {"WINNER_RULE": S.WINNER_RULE, "THEME_RULE": S.THEME_RULE,
         "QUOTE_RULE": S.QUOTE_RULE, "NEITHER_RULE": S.NEITHER_RULE}
for name, text in rules.items():
    check(f"{name} is defined once in the schema and read into the prompt",
          text in rendered and text not in PROMPT_TEMPLATE)
order = ", then ".join(c.value for c in S.CATEGORY_PRIORITY)
check("winner rule order comes from CATEGORY_PRIORITY", order in S.WINNER_RULE, order)
props = S.ReviewTag.model_json_schema()["properties"]
check("field descriptions the model sees reuse the same rule text",
      S.QUOTE_RULE in props["quote"]["description"]
      and S.THEME_RULE in props["theme"]["description"]
      and S.NEITHER_RULE in props["impact_score"]["description"])

# 5. The LangChain template the chain plugs in, rendered for a real review
check("TAGGING_PROMPT is a LangChain PromptTemplate", isinstance(TAGGING_PROMPT, PromptTemplate))
check("its only input variable is review_text", TAGGING_PROMPT.input_variables == ["review_text"],
      str(TAGGING_PROMPT.input_variables))
invoked = TAGGING_PROMPT.invoke({"review_text": reviews[sample_id]}).to_string()
check("chain-style invoke gives exactly the prompt build_prompt renders", invoked == rendered)
check("every slot is filled", "{" not in rendered and "}" not in rendered)
check("rendered prompt contains the review text exactly", reviews[sample_id] in rendered)
check("rendered prompt shows the threshold values from code",
      all(str(v) in rendered for v in values))

# 6. Schema: one winner per review
# rv_cdf86c6e0b has two flaws (PDF export fails, text lag). Winner = higher impact.
sentence = "PDF export fails at the very end and the whole app is laggy when I drag text around."
winner = {"category": "product_flaw", "theme": "pdf export fails", "impact_score": 9,
          "quote": sentence, "reason": "Export never finishes, which outranks the text lag."}
try:
    tag = S.ReviewTag.model_validate(winner)
    check("schema accepts one winning tag for a two-issue review", True,
          f"{tag.theme} -> {tag.severity.value}")
    check("the winning quote is a real sentence of that review", tag.quote in reviews[sample_id])
except ValidationError as e:
    check("schema accepts one winning tag for a two-issue review", False, str(e))

bad_cases = {
    "a list of two findings": {"findings": [winner, winner]},
    "an extra field next to the winner": {**winner, "second_issue": "text box lag"},
    "neither with an impact score": {"category": "neither", "impact_score": 3,
                                     "quote": "x", "reason": "x"},
    "flaw without an impact score": {"category": "product_flaw", "theme": "crash",
                                     "quote": "x", "reason": "x"},
    "score above the scale": {**winner, "impact_score": S.IMPACT_SCORE_MAX + 1},
    "unknown category": {**winner, "category": "bug"},
}
for name, data in bad_cases.items():
    try:
        S.ReviewTag.model_validate(data)
        check(f"schema rejects: {name}", False, "was accepted")
    except ValidationError:
        check(f"schema rejects: {name}", True)

summary = f"{sum(results)}/{len(results)} checks passed"
print(f"\n{summary}")

# ---------------------------------------------------------------------------
# Saved printout: what a reviewer needs to trust the prompt without running it
# ---------------------------------------------------------------------------
rule = "=" * 78
fields = {name: (p.get("type") or p.get("anyOf") or p.get("$ref"), p.get("description", ""))
          for name, p in props.items()}
example_lines = [f"  {cat:<16} {rid}  {reviews[rid][:70]}..." for cat, rid in EXAMPLE_REVIEW_IDS.items()]
field_lines = [f"  {name:<13} {desc}" for name, (_, desc) in fields.items()]

report = "\n".join([
    "STAGE 2 TAGGING RULES - CHECK REPORT",
    f"Result: {summary}",
    "",
    rule,
    "1. SEVERITY THRESHOLDS (named constants in tagging_schema.py)",
    rule,
    f"  Impact score scale: IMPACT_SCORE_MIN={S.IMPACT_SCORE_MIN} to IMPACT_SCORE_MAX={S.IMPACT_SCORE_MAX}",
    *(f"  {n} = {v}" for n, v in zip(names, values)),
    f"  Score -> severity: {mapping}",
    "",
    rule,
    "2. CATEGORY EXAMPLES IN THE PROMPT (real reviews from the export)",
    rule,
    *example_lines,
    "",
    rule,
    "3. OUTPUT SCHEMA: ReviewTag (one tag per review; fields the model fills in)",
    rule,
    *field_lines,
    "",
    rule,
    "4. CHECK RESULTS",
    rule,
    *check_lines,
    "",
    rule,
    f"5. FILLED PROMPT FOR A REAL REVIEW ({sample_id})",
    "   Exactly what TAGGING_PROMPT.invoke({'review_text': ...}) sends to the model.",
    rule,
    rendered,
    rule,
    "",
])
with open(REPORT, "w", encoding="utf-8") as f:
    f.write(report)
print(f"Saved report to {REPORT}")

sys.exit(0 if all(results) else 1)