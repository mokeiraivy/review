"""
Checks the stage 2 tagging rules without calling any model, and saves a report
to output/tagging_rules_check.txt so a reviewer can read it without running it.

Run:  python check_tagging_rules.py

1. Each category example in the prompt is a real review, word for word.
2. The prompt never mentions severity and contains no hard-coded numbers.
3. Severity thresholds are named mention-count constants in code, and severity
   is worked out per theme from how many reviews mention it.
4. Every rule the code enforces is written once, in tagging_schema.py, and the
   prompt and field descriptions read it from there.
5. TAGGING_PROMPT is a LangChain PromptTemplate with review_text as its only input.
6. The schema accepts one tag per review (no severity, no score) and defines the
   quote for neither reviews.
"""

import re
import sys

import pandas as pd
from langchain_core.prompts import PromptTemplate
from pydantic import ValidationError

import tagging_schema as S
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
sample_id = "rv_cdf86c6e0b"
rendered = build_prompt(reviews[sample_id])

# 1. Examples are real reviews, copied exactly
for category, rid in EXAMPLE_REVIEW_IDS.items():
    text = reviews.get(rid)
    check(f"{category} example {rid} is in the export and appears verbatim in the prompt",
          text is not None and text in PROMPT_TEMPLATE)

# 2. The model is never asked about severity; no numbers in the template
check("prompt never asks the model for a severity or score",
      not re.search(r"severity|impact|score", rendered, re.I))
digits = re.findall(r"\d", PROMPT_TEMPLATE)
check("prompt template has no hard-coded numbers", not digits, f"found {digits}" if digits else "")

# 3. Thresholds are named mention-count constants, applied per theme
names = ["HIGH_MIN_MENTIONS", "MEDIUM_MIN_MENTIONS", "LOW_MIN_MENTIONS"]
values = [getattr(S, n) for n in names]
check("three severity thresholds are named int constants in tagging_schema.py",
      all(isinstance(v, int) for v in values),
      ", ".join(f"{n}={v}" for n, v in zip(names, values)))
check("thresholds match the spec: high >= 5 mentions, medium 2-4, low 1",
      (S.HIGH_MIN_MENTIONS, S.MEDIUM_MIN_MENTIONS, S.LOW_MIN_MENTIONS) == (5, 2, 1))
mapping = {n: (S.severity_label(n).value if S.severity_label(n) else "none") for n in range(0, 8)}
check("mention count -> severity follows the thresholds",
      mapping == {0: "none", 1: "low", 2: "medium", 3: "medium", 4: "medium",
                  5: "high", 6: "high", 7: "high"}, str(mapping))


def tag(category, theme, quote="x"):
    return S.ReviewTag(category=category, theme=theme, quote=quote, reason="x")


# A crash six users hit must rank above a crash one user hit once.
demo_tags = ([tag("product_flaw", "app crashes")] * 6
             + [tag("product_flaw", "freezes on open")]
             + [tag("product_flaw", "mp4 export stuck")] * 3
             + [tag("feature_request", "brand kit on mobile")] * 2
             + [tag("neither", None)] * 4)
summary = S.theme_summary(demo_tags)
by_theme = {r["theme"]: r for r in summary}
check("severity is per theme from mention counts (six crash reviews -> high, one -> low)",
      by_theme["app crashes"]["severity"] == "high"
      and by_theme["freezes on open"]["severity"] == "low"
      and by_theme["mp4 export stuck"]["severity"] == "medium")
check("neither tags are not counted as a theme", all(r["category"] != "neither" for r in summary))

# 4. Rules written once, in the schema
rules = {"WINNER_RULE": S.WINNER_RULE, "THEME_RULE": S.THEME_RULE,
         "QUOTE_RULE": S.QUOTE_RULE, "NEITHER_QUOTE_RULE": S.NEITHER_QUOTE_RULE}
for name, text in rules.items():
    check(f"{name} is defined once in the schema and read into the prompt",
          text in rendered and text not in PROMPT_TEMPLATE)
order = ", then ".join(c.value for c in S.CATEGORY_PRIORITY)
check("winner rule order comes from CATEGORY_PRIORITY", order in S.WINNER_RULE, order)
props = S.ReviewTag.model_json_schema()["properties"]
check("field descriptions the model sees reuse the same rule text",
      S.THEME_RULE in props["theme"]["description"]
      and S.QUOTE_RULE in props["quote"]["description"]
      and S.NEITHER_QUOTE_RULE in props["quote"]["description"])
check("model output fields are exactly category, theme, quote, reason",
      list(props) == ["category", "theme", "quote", "reason"], str(list(props)))

# 5. The LangChain template the chain plugs in
check("TAGGING_PROMPT is a LangChain PromptTemplate", isinstance(TAGGING_PROMPT, PromptTemplate))
check("its only input variable is review_text", TAGGING_PROMPT.input_variables == ["review_text"],
      str(TAGGING_PROMPT.input_variables))
invoked = TAGGING_PROMPT.invoke({"review_text": reviews[sample_id]}).to_string()
check("chain-style invoke gives exactly the prompt build_prompt renders", invoked == rendered)
check("every slot is filled", "{" not in rendered and "}" not in rendered)
check("rendered prompt contains the review text exactly", reviews[sample_id] in rendered)

# 6. Schema: one tag per review, including what quote holds for neither
sentence = "PDF export fails at the very end and the whole app is laggy when I drag text around."
winner = {"category": "product_flaw", "theme": "pdf export fails",
          "quote": sentence, "reason": "Export failure is mentioned first."}
try:
    t = S.ReviewTag.model_validate(winner)
    check("schema accepts one tag for a two-issue review (first-mentioned flaw wins)", True, t.theme)
    check("the winning quote is a real sentence of that review", t.quote in reviews[sample_id])
except ValidationError as e:
    check("schema accepts one tag for a two-issue review (first-mentioned flaw wins)", False, str(e))

neither_id = EXAMPLE_REVIEW_IDS["neither"]
neither_quote = ("Only wish the background remover was on the free plan, "
                 "even a few uses a month would be nice")
try:
    n = S.ReviewTag.model_validate({"category": "neither", "quote": neither_quote,
                                    "reason": "Praise plus a wish about the free plan."})
    check("schema accepts a neither tag whose quote is a real sentence showing why",
          n.quote in reviews[neither_id])
except ValidationError as e:
    check("schema accepts a neither tag whose quote is a real sentence showing why", False, str(e))

bad_cases = {
    "a severity field from the model": {**winner, "severity": "high"},
    "an impact score from the model": {**winner, "impact_score": 9},
    "a list of two findings": {"findings": [winner, winner]},
    "neither with an empty quote": {"category": "neither", "quote": "  ", "reason": "x"},
    "neither with a theme": {"category": "neither", "theme": "pricing", "quote": "x", "reason": "x"},
    "flaw without a theme": {"category": "product_flaw", "quote": "x", "reason": "x"},
    "unknown category": {**winner, "category": "bug"},
}
for name, data in bad_cases.items():
    try:
        S.ReviewTag.model_validate(data)
        check(f"schema rejects: {name}", False, "was accepted")
    except ValidationError:
        check(f"schema rejects: {name}", True)

result = f"{sum(results)}/{len(results)} checks passed"
print(f"\n{result}")

# ---------------------------------------------------------------------------
# Saved report: what a reviewer needs to trust the rules without running them
# ---------------------------------------------------------------------------
rule = "=" * 78
summary_lines = [f"  {r['category']:<16} {r['theme']:<22} mentions={r['mentions']:<3} severity={r['severity']}"
                 for r in summary]
report = "\n".join([
    "STAGE 2 TAGGING RULES - CHECK REPORT",
    f"Result: {result}",
    "",
    rule,
    "1. SEVERITY (decided in code per theme from mention counts; the model never sees it)",
    rule,
    *(f"  {n} = {v}" for n, v in zip(names, values)),
    f"  Mentions -> severity: {mapping}",
    "  Worked example (demo tags, not this week's data):",
    *summary_lines,
    "",
    rule,
    "2. CATEGORY EXAMPLES IN THE PROMPT (real reviews from the export)",
    rule,
    *(f"  {cat:<16} {rid}  {reviews[rid][:70]}..." for cat, rid in EXAMPLE_REVIEW_IDS.items()),
    "",
    rule,
    "3. OUTPUT SCHEMA: ReviewTag (one tag per review; the fields the model fills in)",
    rule,
    *(f"  {name:<9} {p.get('description', '')}" for name, p in props.items()),
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