"""
Stage 2 output schema: the fixed list of fields the language model fills in
for every review.

This file is the single authoritative place for the tagging rules that code
enforces. The prompt (tagging_prompt.py) does not restate them; it reads the
rule text and numbers from the constants here. Change a rule here and the
prompt, the field descriptions and the validation all change with it.

One review -> exactly one ReviewTag (one winner). The model does NOT decide
the severity label: it gives an impact score, and severity_label() turns that
score into a label using the three named thresholds below.

The review_id is not asked from the model. The tagging chain attaches it in
code, so a model typo can never point a tag at the wrong review.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Impact score scale (what the model fills in)
# ---------------------------------------------------------------------------
IMPACT_SCORE_MIN = 1
IMPACT_SCORE_MAX = 10

# ---------------------------------------------------------------------------
# Severity thresholds (code turns the score into a label)
#   score >= CRITICAL_THRESHOLD           -> "critical"
#   HIGH_THRESHOLD   <= score < CRITICAL  -> "high"
#   MEDIUM_THRESHOLD <= score < HIGH      -> "medium"
#   score <  MEDIUM_THRESHOLD             -> "low"
# ---------------------------------------------------------------------------
MEDIUM_THRESHOLD = 4
HIGH_THRESHOLD = 7
CRITICAL_THRESHOLD = 9

assert IMPACT_SCORE_MIN < MEDIUM_THRESHOLD < HIGH_THRESHOLD < CRITICAL_THRESHOLD <= IMPACT_SCORE_MAX, \
    "Severity thresholds must be in increasing order inside the impact score scale"


class Category(str, Enum):
    PRODUCT_FLAW = "product_flaw"
    FEATURE_REQUEST = "feature_request"
    NEITHER = "neither"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# One winner per review
# When a review raises more than one thing, the model returns ONE tag: the
# category that comes first in CATEGORY_PRIORITY, and within that category
# the issue with the highest impact score. Broken things outrank wishes,
# because a flaw is hurting users now.
# ---------------------------------------------------------------------------
CATEGORY_PRIORITY = (Category.PRODUCT_FLAW, Category.FEATURE_REQUEST, Category.NEITHER)

WINNER_RULE = (
    "Return exactly ONE tag per review. If the review raises more than one issue, "
    "pick the winner like this: choose the category that comes first in this order: "
    + ", then ".join(c.value for c in CATEGORY_PRIORITY)
    + ". If several issues share that category, choose the one with the highest impact score. "
    "Ignore the other issues; do not mention them in the tag."
)

# ---------------------------------------------------------------------------
# Field rules (used both as the field descriptions the model sees and in the
# prompt text, so they are written only once)
# ---------------------------------------------------------------------------
THEME_RULE = (
    "A short lowercase label naming the feature and the problem or wish, such as "
    "'pdf export fails', 'text box lag', 'pro items not marked', 'brand kit on mobile'. "
    "Use the same wording for the same problem every time."
)
QUOTE_RULE = (
    "Copy ONE sentence from the review that shows the winning issue, exactly as written: "
    "same spelling, capitals, punctuation and spacing. Never reword, shorten, merge "
    "sentences or fix typos. If you cannot copy it exactly, choose a different sentence."
)
NEITHER_RULE = "For neither, leave theme and impact_score empty."
REASON_RULE = "One short sentence explaining why this category, issue and score were chosen."


def severity_label(impact_score: Optional[int]) -> Optional[Severity]:
    """Map an impact score to a severity label using the named thresholds."""
    if impact_score is None:
        return None
    if impact_score >= CRITICAL_THRESHOLD:
        return Severity.CRITICAL
    if impact_score >= HIGH_THRESHOLD:
        return Severity.HIGH
    if impact_score >= MEDIUM_THRESHOLD:
        return Severity.MEDIUM
    return Severity.LOW


class ReviewTag(BaseModel):
    """The one tag the model returns for one review (the winner)."""

    model_config = {"extra": "forbid"}

    category: Category = Field(
        description="product_flaw, feature_request, or neither, as defined in the instructions."
    )
    theme: Optional[str] = Field(default=None, description=f"{THEME_RULE} {NEITHER_RULE}")
    impact_score: Optional[int] = Field(
        default=None,
        ge=IMPACT_SCORE_MIN,
        le=IMPACT_SCORE_MAX,
        description=f"How badly the winning issue hurts the user, using the impact scale in "
                    f"the instructions. {NEITHER_RULE}",
    )
    quote: str = Field(description=QUOTE_RULE)
    reason: str = Field(description=REASON_RULE)

    @model_validator(mode="after")
    def check_fields_match_category(self):
        if self.category == Category.NEITHER:
            if self.impact_score is not None or self.theme:
                raise ValueError(NEITHER_RULE)
        else:
            if self.impact_score is None:
                raise ValueError(f"A {self.category.value} tag needs an impact_score")
            if not self.theme or not self.theme.strip():
                raise ValueError(f"A {self.category.value} tag needs a theme")
        if not self.quote.strip():
            raise ValueError("quote must not be empty")
        return self

    @property
    def severity(self) -> Optional[Severity]:
        return severity_label(self.impact_score)