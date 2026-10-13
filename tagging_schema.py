"""
Stage 2 output schema: the fixed list of fields the language model fills in
for every review, and the rules code enforces on them.

This file is the single authoritative place for those rules. The prompt
(tagging_prompt.py) does not restate them; it reads the rule text from the
constants here.

SEVERITY IS NOT THE MODEL'S JOB. On the dashboard card the number next to the
severity call is the mention count: how many reviews raised that theme. So
severity is decided in code, per theme, by comparing the mention count with the
three named thresholds below. The model only tags each review (category, theme,
quote, reason); it never sees or names a severity.

The review_id is not asked from the model. The tagging chain attaches it in
code, so a model typo can never point a tag at the wrong review.
"""

from collections import Counter
from enum import Enum
from typing import Iterable, Optional

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Severity thresholds: mention counts per theme (decided in code, never by the model)
#   mentions >= HIGH_MIN_MENTIONS                        -> "high"
#   MEDIUM_MIN_MENTIONS <= mentions < HIGH_MIN_MENTIONS  -> "medium"
#   LOW_MIN_MENTIONS    <= mentions < MEDIUM_MIN_MENTIONS-> "low"
# ---------------------------------------------------------------------------
HIGH_MIN_MENTIONS = 5
MEDIUM_MIN_MENTIONS = 2
LOW_MIN_MENTIONS = 1

assert LOW_MIN_MENTIONS < MEDIUM_MIN_MENTIONS < HIGH_MIN_MENTIONS, \
    "Severity thresholds must be in increasing order"


class Category(str, Enum):
    PRODUCT_FLAW = "product_flaw"
    FEATURE_REQUEST = "feature_request"
    NEITHER = "neither"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def severity_label(mention_count: int) -> Optional[Severity]:
    """Severity for one theme, from how many reviews mentioned it this week."""
    if mention_count >= HIGH_MIN_MENTIONS:
        return Severity.HIGH
    if mention_count >= MEDIUM_MIN_MENTIONS:
        return Severity.MEDIUM
    if mention_count >= LOW_MIN_MENTIONS:
        return Severity.LOW
    return None


# ---------------------------------------------------------------------------
# One winner per review
# When a review raises more than one thing, the model returns ONE tag: the
# category that comes first in CATEGORY_PRIORITY (broken things outrank
# wishes, because a flaw is hurting users now). Within that category, the
# issue the review mentions first wins. No hidden per-review score.
# ---------------------------------------------------------------------------
CATEGORY_PRIORITY = (Category.PRODUCT_FLAW, Category.FEATURE_REQUEST, Category.NEITHER)

WINNER_RULE = (
    "Return exactly ONE tag per review. If the review raises more than one issue, "
    "pick the winner like this: choose the category that comes first in this order: "
    + ", then ".join(c.value for c in CATEGORY_PRIORITY)
    + ". If several issues share that category, choose the one the review mentions first. "
    "Ignore the other issues; do not mention them in the tag."
)

# ---------------------------------------------------------------------------
# Field rules (used both as the field descriptions the model sees and in the
# prompt text, so they are written only once)
# ---------------------------------------------------------------------------
THEME_RULE = (
    "A short lowercase label naming the feature and the problem or wish, such as "
    "'pdf export fails', 'text box lag', 'pro items not marked', 'brand kit on mobile'. "
    "Use the same wording for the same problem every time, because reviews are "
    "counted by theme. For neither, leave theme empty."
)
QUOTE_RULE = (
    "Copy ONE sentence from the review exactly as written: same spelling, capitals, "
    "punctuation and spacing. Never reword, shorten, merge sentences or fix typos. "
    "If you cannot copy it exactly, choose a different sentence. "
    "For product_flaw or feature_request, copy the sentence that shows the winning issue."
)
NEITHER_QUOTE_RULE = (
    "For neither, leave quote empty. Do not copy or invent a sentence: a neither review "
    "has no flaw or request to quote, and it never appears on a dashboard card."
)
REASON_RULE = "One short sentence explaining why this category and theme were chosen."


class ReviewTag(BaseModel):
    """The one tag the model returns for one review (the winner). No severity."""

    model_config = {"extra": "forbid"}

    category: Category = Field(
        description="product_flaw, feature_request, or neither, as defined in the instructions."
    )
    theme: Optional[str] = Field(default=None, description=THEME_RULE)
    quote: Optional[str] = Field(default=None, description=f"{QUOTE_RULE} {NEITHER_QUOTE_RULE}")
    reason: str = Field(description=REASON_RULE)

    @model_validator(mode="after")
    def check_fields_match_category(self):
        if self.category == Category.NEITHER:
            if (self.theme or "").strip():
                raise ValueError("A neither tag must keep theme empty, not invent one")
            if (self.quote or "").strip():
                raise ValueError("A neither tag must keep quote empty, not invent one")
            self.theme, self.quote = None, None
        else:
            if not (self.theme or "").strip():
                raise ValueError(f"A {self.category.value} tag needs a theme")
            if not (self.quote or "").strip():
                raise ValueError(f"A {self.category.value} tag needs a quote")
        return self


def theme_summary(tags: Iterable[ReviewTag]) -> list[dict]:
    """Count mentions per (category, theme) across all tagged reviews and attach
    the severity from the thresholds. This is the number the PM reads next to
    the severity on each card. 'neither' tags are not counted."""
    counts = Counter(
        (t.category, t.theme.strip().lower())
        for t in tags if t.category != Category.NEITHER
    )
    rows = [
        {"category": cat.value, "theme": theme, "mentions": n,
         "severity": severity_label(n).value}
        for (cat, theme), n in counts.items()
    ]
    return sorted(rows, key=lambda r: (r["category"], -r["mentions"], r["theme"]))