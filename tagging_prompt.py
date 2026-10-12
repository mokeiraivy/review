"""
Stage 2 prompt template: the fixed instruction sent to the language model for
every review. The only slot that changes per review is {review_text}.

Rules that code also enforces are NOT written in this text. build_prompt()
fills them in from tagging_schema.py: the impact scale numbers, the
one-winner rule, and the theme / quote / neither field rules. Each rule lives
in one place (the schema) and the prompt can never drift away from it.

The three example reviews are copied word for word from the export. Their
review_ids are listed in EXAMPLE_REVIEW_IDS so check_tagging_rules.py can
prove each one is real.
"""

from tagging_schema import (
    CRITICAL_THRESHOLD,
    HIGH_THRESHOLD,
    IMPACT_SCORE_MAX,
    IMPACT_SCORE_MIN,
    MEDIUM_THRESHOLD,
    NEITHER_RULE,
    QUOTE_RULE,
    THEME_RULE,
    WINNER_RULE,
)

# Which real review is used as the example for each category.
EXAMPLE_REVIEW_IDS = {
    "product_flaw": "rv_36484054c9",
    "feature_request": "rv_e209f393ab",
    "neither": "rv_5e547992d8",
}

PROMPT_TEMPLATE = """\
You are tagging app store reviews of the Canva mobile editor (iOS and Android) \
for a weekly product review. Read ONE review and return ONE tag for it, \
following these rules exactly.

## Categories

**product_flaw** - Something that exists in the mobile editor does not work the \
way a user can reasonably expect: it fails, crashes, freezes, lags, loses work, \
or hides information the user needs until it is too late (for example, only \
revealing that an element is Pro at download time). A review is still a flaw \
when the user also suggests a fix; judge the problem, not the suggestion.
Example (product_flaw):
"there's no way to tell which fonts and graphics are Pro until you try to save. \
I'm on free and ended up redoing my whole invite. put a crown on them or something"
Why: it ends with a suggestion, but the core problem is that the editor hides \
which items are Pro until the user tries to save, and the user lost work.

**feature_request** - The user wants a capability the mobile editor does not \
have yet, often one that exists on desktop. Nothing is broken; something new \
would have to be built. Wording like "can't find" or "doesn't work" can still \
be a request when the thing was never in the mobile editor.
Example (feature_request):
"The new editor looks great but I can't find my brand kit anywhere. I have to \
type in our hex codes by hand every time. Please add brand kit to mobile"
Why: "can't find" sounds like a bug, but brand kit is not in the mobile editor \
and the user asks for it to be added.

**neither** - The review has no product flaw and no feature request: praise, \
general comments, or wishes about pricing and which plan includes a feature \
(a business decision, not something the editor team builds or fixes).
Example (neither):
"Really like the new editor, it's way faster to find templates. Only wish the \
background remover was on the free plan, even a few uses a month would be nice"
Why: it is praise plus a wish to change what the free plan includes. Nothing is \
broken and nothing new needs building.

## Deciding rules
- Flaw or request? Ask: would fixing a bug make this user happy (product_flaw), \
or would Canva have to build something new (feature_request)?
- Paywall: being surprised by Pro content too late is a product_flaw. Asking \
for a Pro feature to be free, on its own, is neither.
- Use neither only when the review has no flaw and no request.
- Judge only the review text. Do not guess facts the review does not state.

## One winner
{winner_rule}

## Impact score (for product_flaw and feature_request)
Score how badly the winning issue hurts the user, from {score_min} to {score_max}:
- {critical_min} to {score_max}: the app crashes or freezes, the user loses work, \
or the user cannot finish the task in the app at all.
- {high_min} to {high_max}: a core task fails repeatedly or only works with a \
workaround, or a core tool is unusable.
- {medium_min} to {medium_max}: noticeable friction (lag, confusion, surprise \
paywall, extra manual steps), but the task still gets done.
- {score_min} to {low_max}: minor or cosmetic, or a nice-to-have.
{neither_rule}

## Theme
{theme_rule}

## Quote
{quote_rule}

## Review to tag
<review>
{review_text}
</review>
"""


def build_prompt(review_text: str) -> str:
    """Fill the template for one review. Rules and numbers come from tagging_schema."""
    return PROMPT_TEMPLATE.format(
        review_text=review_text,
        winner_rule=WINNER_RULE,
        theme_rule=THEME_RULE,
        quote_rule=QUOTE_RULE,
        neither_rule=NEITHER_RULE,
        score_min=IMPACT_SCORE_MIN,
        score_max=IMPACT_SCORE_MAX,
        critical_min=CRITICAL_THRESHOLD,
        high_min=HIGH_THRESHOLD,
        high_max=CRITICAL_THRESHOLD - 1,
        medium_min=MEDIUM_THRESHOLD,
        medium_max=HIGH_THRESHOLD - 1,
        low_max=MEDIUM_THRESHOLD - 1,
    )