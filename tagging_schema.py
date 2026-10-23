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
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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
# ---------------------------------------------------------------------------
# Theme catalogue (stage 4 fix, from audit/tag_audit.csv)
# Each review is tagged in a separate call, so the model never sees the themes it
# gave earlier reviews; free-text themes split one problem into several labels
# (audit findings F1-F3) and let a request be worded as a fault (F4). The model
# now picks a theme from this fixed list, and the schema rejects anything else.
# Each theme belongs to exactly one category. "other ..." catches a problem the
# list does not cover yet; the run log lists those rows so the list can grow.
# ---------------------------------------------------------------------------
OTHER_FLAW = "other flaw"
OTHER_REQUEST = "other request"
THEME_CATALOGUE = {
    Category.PRODUCT_FLAW: {
        "app crashes": "the app closes itself, or freezes and then closes, whatever triggered it "
                       "(opening a template, adding photos, opening a large design)",              # F3
        "text box lag": "typing in or moving a text box is slow, delayed, jumpy or choppy",
        "pdf export fails": "PDF export does not complete: it errors or stops near the end. "
                            "Slow but finishing is NOT this theme (use other flaw)",
        "mp4 export stuck at 99%": "MP4 / video export stalls or stops at 99% and never finishes",  # F1
        "pro items not marked": "the user only learns that an element, font, sticker or tool is Pro "
                                "when saving or downloading",                                      # F2
        OTHER_FLAW: "a flaw that fits none of the themes above",
    },
    Category.FEATURE_REQUEST: {
        "keyboard shortcuts on ipad": "wants keyboard shortcuts to work with a keyboard on iPad",   # F4
        "layers panel on mobile": "wants the desktop layers panel in the mobile editor",
        "brand kit on mobile": "wants brand kit (saved brand colours, fonts) in the mobile editor",
        OTHER_REQUEST: "a request that fits none of the themes above",
    },
}
ALL_THEMES = tuple(t for themes in THEME_CATALOGUE.values() for t in themes)
ThemeName = Literal[ALL_THEMES]  # becomes an enum in the schema the model fills in


def _catalogue_text():
    lines = []
    for cat, themes in THEME_CATALOGUE.items():
        lines.append(f"For {cat.value}, use one of:")
        lines += [f"- '{name}': {meaning}" for name, meaning in themes.items()]
    return "\n".join(lines)


THEME_RULE = (
    "Pick the theme from this fixed list, copied exactly. Name the problem, not what "
    "triggered it, and use the same theme for the same problem even if the review words "
    "it differently. A feature_request theme names the wish, never a fault. Use 'other "
    "flaw' or 'other request' only when nothing in the list fits. For neither, leave "
    "theme empty.\n" + _catalogue_text()
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
    theme: Optional[ThemeName] = Field(default=None, description=THEME_RULE)
    quote: Optional[str] = Field(default=None, description=f"{QUOTE_RULE} {NEITHER_QUOTE_RULE}")
    reason: str = Field(description=REASON_RULE)

    @field_validator("theme", "quote", mode="before")
    @classmethod
    def blank_is_empty(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode="after")
    def check_fields_match_category(self):
        if self.category == Category.NEITHER:
            if self.theme:
                raise ValueError("A neither tag must keep theme empty, not invent one")
            if (self.quote or "").strip():
                raise ValueError("A neither tag must keep quote empty, not invent one")
            self.theme, self.quote = None, None
        else:
            if not self.theme:
                raise ValueError(f"A {self.category.value} tag needs a theme")
            if self.theme not in THEME_CATALOGUE[self.category]:
                raise ValueError(f"Theme '{self.theme}' does not belong to {self.category.value}")
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