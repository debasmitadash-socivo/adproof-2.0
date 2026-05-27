"""Specific, actionable copy critique with before/after suggestions.

Runs cheap heuristic checks against the headline / primary text / CTA / link
for each ad and returns concrete issues with severity + a fix.

This is NOT a spell-checker -- it's a marketer-aware copy critic. It catches:

* length violations vs the chosen format
* ALL-CAPS shouting in headlines
* generic / weak CTAs ("Shop now", "Learn more")
* missing concrete numbers (the most-tested CTR lift)
* platform-tone mismatch (exclamations on LinkedIn read consumer-y)
* missing punctuation, double spaces
* destination URL hygiene (no scheme, no tracking)
* missing required slots for the format
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import List, Optional


@dataclass
class CopyIssue:
    severity: str       # error | warning | info
    field: str          # headline | primary_text | description | cta | link | copy
    message: str
    fix: str
    lift_pct: Optional[int] = None  # approx CTR lift if fixed (directional)

    def to_dict(self) -> dict:
        return asdict(self)


_WEAK_CTAS = {
    "click here", "learn more", "shop now", "buy now",
    "find out more", "read more", "see more", "get started", "see now",
}

# Light-touch B2B platform check.
_B2B_PLATFORM_IDS = {"linkedin"}

_GENERIC_PHRASES = {
    "introducing", "we are excited", "we're excited", "limited time only",
    "act fast", "incredible offer", "best in class", "world-class",
}


def _is_mostly_uppercase(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4:
        return False
    upper = [c for c in letters if c.isupper()]
    return len(upper) / len(letters) > 0.6


def _has_concrete_numbers(text: str) -> bool:
    """Catches '50%', '7 days', '$40', '12k+', 'one in three'."""
    if re.search(r"\d", text or ""):
        return True
    return bool(re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve|hundred|thousand|million)\b",
        (text or "").lower(),
    ))


def critique_copy(
    headline: str,
    primary_text: str,
    description: str,
    cta: str,
    link: str,
    fmt,
    profile=None,
) -> List[CopyIssue]:
    """Return a prioritised list of copy issues with concrete fixes."""
    issues: List[CopyIssue] = []
    full_copy = " ".join(t for t in (headline, primary_text, description) if t)

    # --- Length vs format ---
    limits = getattr(fmt, "copy_limits", {}) or {}
    if "headline_chars" in limits and headline and \
            len(headline) > limits["headline_chars"]:
        issues.append(CopyIssue(
            severity="error", field="headline",
            message=f'Headline is {len(headline)} chars; {fmt.name} truncates at {limits["headline_chars"]}.',
            fix=f"Trim to {limits['headline_chars']} characters or fewer. Lead with the benefit, push the brand to the end.",
        ))
    if "primary_text_chars" in limits and primary_text and \
            len(primary_text) > limits["primary_text_chars"]:
        issues.append(CopyIssue(
            severity="warning", field="primary_text",
            message=f'Primary text is {len(primary_text)} chars; {fmt.name} truncates at {limits["primary_text_chars"]}.',
            fix=f"Trim to ≤{limits['primary_text_chars']} characters — readers won't see the cut-off bit.",
        ))
    if "description_chars" in limits and description and \
            len(description) > limits["description_chars"]:
        issues.append(CopyIssue(
            severity="warning", field="description",
            message=f"Description is over the {limits['description_chars']}-char limit.",
            fix="Cut it down — anything past the cap is hidden.",
        ))

    # --- Required slots ---
    if "min_headlines" in limits:
        # Search ads need multiple headlines; we only collect one in v1.
        issues.append(CopyIssue(
            severity="info", field="headline",
            message=f"{fmt.name} needs {limits['min_headlines']}+ headlines to enter the auction.",
            fix="In v1 we score one headline. v1.1 will let you enter the full set of 3-15 headlines + 2-4 descriptions.",
        ))

    # --- ALL-CAPS shouting ---
    if headline and _is_mostly_uppercase(headline):
        issues.append(CopyIssue(
            severity="warning", field="headline",
            message="Headline is mostly uppercase — reads as shouting on most platforms.",
            fix="Use sentence case ('Glow without the guesswork') or title case ('Glow Without The Guesswork').",
            lift_pct=8,
        ))

    # --- Weak / generic CTAs ---
    cta_lower = (cta or "").strip().lower()
    if cta_lower and cta_lower in _WEAK_CTAS:
        category = (getattr(profile, "product_category", "") or "general")
        examples = {
            "fitness": "'Find a class near me' or 'Get my training plan'",
            "beauty": "'Find my routine' or 'Try a sample'",
            "finance": "'See my rate in 60s' or 'Calculate my saving'",
            "travel": "'Find dates that fit' or 'Get my itinerary'",
        }.get(category, "'See if it fits you' or 'Get my [specific outcome]'")
        issues.append(CopyIssue(
            severity="info", field="cta",
            message=f'"{cta}" is one of the most generic CTAs — tested ~15% lower than specific alternatives.',
            fix=f"Try a specific, benefit-led CTA like {examples}.",
            lift_pct=15,
        ))

    # --- No specific numbers anywhere ---
    if full_copy and not _has_concrete_numbers(full_copy):
        issues.append(CopyIssue(
            severity="info", field="primary_text",
            message="No concrete numbers in the copy — no time-frame, no quantity, no specific outcome.",
            fix="Add a specific number ('in 4 weeks', '12,000 customers', '40% off', 'first week free'). Specifics typically lift CTR ~10–15%.",
            lift_pct=12,
        ))

    # --- Generic / cliché phrases ---
    lower_copy = full_copy.lower()
    for phrase in _GENERIC_PHRASES:
        if phrase in lower_copy:
            issues.append(CopyIssue(
                severity="info", field="copy",
                message=f'"{phrase}" is overused — readers tune it out.',
                fix=f'Replace "{phrase}" with a concrete benefit specific to your customer.',
                lift_pct=5,
            ))

    # --- Platform tone mismatch ---
    platform_id = getattr(fmt, "platform_id", "")
    if platform_id in _B2B_PLATFORM_IDS:
        if "!" in (headline + primary_text):
            issues.append(CopyIssue(
                severity="warning", field="copy",
                message="Exclamation marks read consumer-y on LinkedIn — out of step with the platform's tone.",
                fix="Drop the '!' and let the value proposition land flat.",
                lift_pct=4,
            ))
        # Emoji check (heuristic): any non-ASCII run that's not part of a word
        if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", full_copy):
            issues.append(CopyIssue(
                severity="info", field="copy",
                message="Emojis tend to underperform on LinkedIn vs other Meta surfaces.",
                fix="Strip emojis from B2B copy unless the brand is intentionally casual.",
            ))

    # --- Whitespace / punctuation polish ---
    if primary_text and "  " in primary_text:
        issues.append(CopyIssue(
            severity="info", field="primary_text",
            message="Double spaces in the primary text.",
            fix="Collapse to single spaces.",
        ))
    if primary_text and not re.search(r"[.!?]\s*$", primary_text.strip()):
        issues.append(CopyIssue(
            severity="info", field="primary_text",
            message="Primary text doesn't end in punctuation.",
            fix="Close with a period — feels more polished and platform-native.",
        ))
    if headline and re.search(r"[.!?]$", headline.strip()):
        issues.append(CopyIssue(
            severity="info", field="headline",
            message="Headlines rarely end in punctuation — drops scroll-stop.",
            fix="Remove the trailing period / exclamation.",
        ))

    # --- Title-case vs sentence-case consistency on headline ---
    if headline and len(headline.split()) >= 3:
        words = [w for w in headline.split() if w.isalpha()]
        if words:
            title = sum(1 for w in words if w[:1].isupper())
            sentence = sum(1 for w in words if w.islower())
            if 0.3 < title / max(len(words), 1) < 0.75 and sentence > 0:
                issues.append(CopyIssue(
                    severity="info", field="headline",
                    message="Headline mixes sentence-case and title-case capitalisation.",
                    fix="Pick one: 'Glow without the guesswork' (sentence case, recommended) or 'Glow Without the Guesswork' (title case).",
                ))

    # --- Destination URL hygiene ---
    if link:
        url = link.strip()
        if not re.match(r"^https?://", url):
            issues.append(CopyIssue(
                severity="warning", field="link",
                message="Destination URL is missing http(s):// — most ad platforms reject this.",
                fix=f"Set the full URL: https://{url.lstrip('/')}",
            ))
        if "utm_" not in url:
            issues.append(CopyIssue(
                severity="info", field="link",
                message="No UTM parameters on the destination URL.",
                fix="Add UTM params (utm_source / utm_medium / utm_campaign) so this ad's traffic is attributable in GA / Mixpanel.",
            ))

    # --- Headline + body benefit echo ---
    if headline and primary_text and \
            headline.lower().strip() in primary_text.lower():
        issues.append(CopyIssue(
            severity="info", field="primary_text",
            message="Primary text repeats the headline verbatim.",
            fix="Use the body to add the supporting benefit or proof — don't re-state the headline.",
        ))

    # Order most important first.
    SEV_ORDER = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: SEV_ORDER.get(i.severity, 3))
    return issues
