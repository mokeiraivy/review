"""
Stage 2 output schema: the fixed list of fields the language model fills in
for every review.

The model returns one ReviewTagging per review. It does NOT decide the
severity label. It gives an impact score, and severity_label() in this file
turns that score into a label using the three named thresholds below. So the
thresholds live only here, in code, and can be changed in one place.

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


class Finding(BaseModel):
    """One issue raised in a review. A review can contain more than one."""

    category: Category = Field(
        description="product_flaw, feature_request, or neither, as defined in the instructions."
    )
    theme: Optional[str] = Field(
        default=None,
        description="Short lowercase label naming the feature and the problem or wish, "
                    "e.g. 'pdf export fails'. Leave empty when category is neither.",
    )
    impact_score: Optional[int] = Field(
        default=None,
        ge=IMPACT_SCORE_MIN,
        le=IMPACT_SCORE_MAX,
        description="How badly this hurts the user, using the impact scale in the instructions. "
                    "Leave empty when category is neither.",
    )
    quote: str = Field(
        description="One sentence copied from the review exactly, character for character, "
                    "that shows this finding. Do not fix spelling, capitals or punctuation."
    )
    reason: str = Field(
        description="One short sentence explaining why this category and score were chosen."
    )

    @model_validator(mode="after")
    def check_fields_match_category(self):
        if self.category == Category.NEITHER:
            if self.impact_score is not None or self.theme:
                raise ValueError("A 'neither' finding must not have a theme or impact_score")
        else:
            if self.impact_score is None:
                raise ValueError(f"A {self.category.value} finding needs an impact_score")
            if not self.theme or not self.theme.strip():
                raise ValueError(f"A {self.category.value} finding needs a theme")
        if not self.quote.strip():
            raise ValueError("quote must not be empty")
        return self

    @property
    def severity(self) -> Optional[Severity]:
        return severity_label(self.impact_score)


class ReviewTagging(BaseModel):
    """Everything the model returns for one review."""

    findings: list[Finding] = Field(
        min_length=1,
        description="Every flaw or feature request in the review, most severe first. "
                    "If the review has none, a single finding with category neither.",
    )

    @model_validator(mode="after")
    def check_neither_is_alone(self):
        cats = [f.category for f in self.findings]
        if Category.NEITHER in cats and len(cats) > 1:
            raise ValueError("'neither' must be the only finding when it is used")
        return self

    @property
    def primary(self) -> Finding:
        """The finding written to the review's tag column: the highest impact
        score, decided in code rather than trusting the model's ordering."""
        return max(self.findings, key=lambda f: f.impact_score or 0)