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
    source: Optional[str] = None    # "socivo" for Socivo rules; None = built-in

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


# ---------------------------------------------------------------------------
# Text-quality detectors (added 2026-06-10 per owner feedback — VIE wasn't
# catching obvious typos, weird symbols mid-word, or AI smells).
# ---------------------------------------------------------------------------

# AI / corporate-speak phrases that flatten copy. Tuned to the owner's
# personal banned-phrases list (per linkedin-devils-advocate skill) so the
# same critic works for LinkedIn drafts too.
_AI_PHRASES = (
    "game-changer", "game changer", "in today's landscape", "in today's world",
    "let's dive in", "at the end of the day", "seamless", "leverage",
    "unlock", "elevate", "synergy", "circle back", "bandwidth", "low-hanging fruit",
    "boil the ocean", "move the needle", "needs to be addressed", "going forward",
    "robust", "best-in-class", "world-class", "cutting-edge", "next-level",
)

# Likely typos / common misspellings + missing-apostrophe shortcuts.
_TYPO_PATTERNS = (
    (r"\b[Yy]our\s+welcome\b",      "'Your welcome' → 'You're welcome'"),
    (r"\b[Ii]ts\s+a\b",              "'Its a' → 'It's a'"),
    (r"\b[Ii]m\s",                   "'Im ' missing apostrophe — should be 'I'm '"),
    (r"\b[Yy]oure\s",                "'Youre ' missing apostrophe — should be 'You're '"),
    (r"\b[Dd]ont\s",                 "'Dont' missing apostrophe — 'Don't'"),
    (r"\b[Cc]ant\s",                 "'Cant' missing apostrophe — 'Can't'"),
    (r"\b[Ww]ont\s",                 "'Wont' missing apostrophe — 'Won't'"),
    (r"\b[Tt]heir\s+is\b",           "'Their is' → 'There is'"),
    (r"\bteh\b",                     "'teh' is the classic 'the' typo"),
    (r"\brecieve\b",                 "'recieve' is misspelt — 'receive'"),
    (r"\boccured\b",                 "'occured' → 'occurred'"),
    (r"\bdefinately\b",              "'definately' → 'definitely'"),
    (r"\bseperate\b",                "'seperate' → 'separate'"),
    (r"\b(?:loo+|sooo+|reeeally|amaaaazing)\b",
                                      "Stretched-out word reads as informal/text-message style"),
    (r"\b(\w)\1{2,}(\w)*",            "Letter repeated 3+ times in a word — often a typo or chat-speak"),
)

# Symbol-in-word / leet-speak tricks brands use to try to dodge filters or
# add emphasis. These hurt readability AND get clamped by ad-platform policy.
_SYMBOL_IN_WORD = re.compile(
    r"\b[A-Za-z]+[@$0]+[A-Za-z]+\b"            # B@y, m0ney, c@sh
    r"|\b[A-Za-z](?:[._\-*]+[A-Za-z]){2,}\b",  # B.U.Y, B-U-Y, B_U_Y
)

# Emoji clusters (3+ in a row) — heavy in B2C but reads as low-effort spam
# in B2B contexts.
_EMOJI_CLUSTER = re.compile(
    r"(?:[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F☀-➿]\s*){3,}")


def _check_text_quality(text: str, field: str,
                          *, allow_emojis: bool = True,
                          platform_id: str = "") -> List[CopyIssue]:
    """Deterministic quality scan for typos / symbols / repeats / AI smells.

    Honest about confidence: these are pattern checks, NOT a full grammar
    engine. False positives are possible (e.g. 'Mississippi' triggers the
    'letter repeated 3+ times' rule). The fix line always explains the
    suspected issue so the user can dismiss it if it's a false positive.
    """
    out: List[CopyIssue] = []
    if not text:
        return out

    # 1. Runaway punctuation (!!! / ??? / multiple periods that aren't an ellipsis).
    if re.search(r"!{2,}", text):
        out.append(CopyIssue(
            severity="warning", field=field,
            message="Multiple exclamation marks in a row (!!) — reads as spammy on most platforms and gets clamped by Meta's policy filters.",
            fix="Use ONE exclamation maximum, and only where the sentence genuinely earns it.",
        ))
    if re.search(r"\?{2,}", text):
        out.append(CopyIssue(
            severity="info", field=field,
            message="Multiple question marks in a row (??) — reads as agitated, not curious.",
            fix="One question mark. The reader gets it.",
        ))
    if re.search(r"\.{4,}", text):
        out.append(CopyIssue(
            severity="info", field=field,
            message="More than three dots in a row — an ellipsis is exactly three (…).",
            fix="Use exactly three dots, or the unicode … character.",
        ))

    # 2. Symbol-in-word / leet-speak / character-spacing.
    # Note (per owner feedback 2026-06-10): stylistic spacing like "B-U-Y"
    # or "Lim!ted Time" is often DELIBERATE — meant to read weird but
    # meaningful. We surface it as INFO, not warning, and acknowledge it
    # might be intentional. Only flag if there are TWO+ instances (one is
    # likely deliberate; multiple suggests a typo pattern).
    matches = list(_SYMBOL_IN_WORD.finditer(text))
    if len(matches) >= 2:
        examples = ", ".join(f'"{m.group(0)}"' for m in matches[:3])
        out.append(CopyIssue(
            severity="info", field=field,
            message=(f"Multiple symbols inside words: {examples}. If deliberate "
                     "stylistic emphasis (e.g. censorship-skirting on a "
                     "sensitive niche), fine. If accidental, fix."),
            fix="Verify each instance is intentional. Platforms increasingly downrank censor-dodge tricks.",
        ))

    # 3. Emoji clusters (5+ consecutive — bumped from 3). A short emoji run
    # is fine as decoration; only call out when it's clearly excessive.
    # Still stricter on LinkedIn where consumer emoji walls genuinely hurt.
    if _EMOJI_CLUSTER.search(text):
        m = _EMOJI_CLUSTER.search(text)                       # re-scan for matches
        is_b2b = platform_id.lower() in _B2B_PLATFORM_IDS
        cluster_len = len((m.group(0) if m else "").replace(" ", ""))
        threshold = 3 if is_b2b else 5
        if cluster_len >= threshold:
            out.append(CopyIssue(
                severity="info",
                field=field,
                message=(f"Emoji cluster ({cluster_len} in a row)" +
                         (" — reads as low-effort on LinkedIn." if is_b2b else
                          " — fine on consumer feeds but worth thinning for a cleaner read.")),
                fix="Cap at 2 emojis per cluster; use them to mark a beat, not as filler.",
            ))

    # 4. Whitespace + leading/trailing junk.
    if "  " in text:
        out.append(CopyIssue(
            severity="info", field=field,
            message="Double space inside the text — usually a copy-paste artefact.",
            fix="Collapse to single spaces.",
        ))
    if text != text.strip():
        out.append(CopyIssue(
            severity="info", field=field,
            message="Leading or trailing whitespace — gets preserved on some platforms and breaks line-wrap.",
            fix="Trim the start/end.",
        ))

    # 5. Typo & missing-apostrophe patterns.
    lower = text.lower()
    seen_typos = set()
    for pattern, fix_text in _TYPO_PATTERNS:
        m = re.search(pattern, text)
        if m and m.group(0).lower() not in seen_typos:
            seen_typos.add(m.group(0).lower())
            out.append(CopyIssue(
                severity="warning", field=field,
                message=f"Possible typo: \"{m.group(0)}\". {fix_text}.",
                fix=f"Verify the spelling; this pattern usually catches a real mistake but occasionally false-positives on proper nouns.",
            ))
            if len(seen_typos) >= 3:           # Don't drown the user
                break

    # 6. AI / corporate-speak phrases.
    ai_hits = [phrase for phrase in _AI_PHRASES if phrase in lower]
    if ai_hits:
        quoted = ", ".join('"' + p + '"' for p in ai_hits[:3])
        more = "…" if len(ai_hits) > 3 else ""
        out.append(CopyIssue(
            severity="info", field=field,
            message=(f"AI / corporate-speak phrases detected: {quoted}{more}. "
                     f"These flatten copy and reduce trust (Hootsuite 2026: "
                     f"30% of consumers are less likely to buy if ads feel "
                     f"AI-generated)."),
            fix="Rewrite in plain English. Specific, concrete language beats corporate phrases.",
            lift_pct=6,
        ))

    # 7. Em-dash detection (per owner's UK-spelling/no-em-dashes preference
    # for LinkedIn-style drafts). Soft warning — only flags if there's more
    # than one em-dash, since the occasional em-dash is fine in long-form.
    em_dashes = text.count("—") + text.count("–")
    if em_dashes >= 2:
        out.append(CopyIssue(
            severity="info", field=field,
            message=f"{em_dashes} em / en dashes in the copy — heavy em-dash usage reads as AI-generated to many readers (it's a common LLM tell).",
            fix="Replace with a comma, full stop, or line break. Em-dashes are fine occasionally but not as a default punctuation.",
        ))
    return out


# ---------------------------------------------------------------------------
# Socivo ad-copywriting.md detectors (Session 3). ADDITIVE — these run
# alongside the existing owner-calibrated checks, never replacing them. Each
# emits source="socivo" so the UI can attribute. Knowledge base adapted from
# Socivo's, licensed for AdProof's use.
# ---------------------------------------------------------------------------

# Mistake #5 — vague outcome language: promises a result without saying what
# changes or by how much. Multi-word clichés kept DISTINCT from _AI_PHRASES /
# _GENERIC_PHRASES so we never double-flag the same words.
_VAGUE_OUTCOME = (
    "make smarter decisions", "drive results", "drive real results",
    "deliver results", "achieve your goals", "reach your goals",
    "take it to the next level", "boost your bottom line", "supercharge your",
    "transform your business", "transform the way you work", "get more done",
    "work smarter", "increase productivity", "improve efficiency",
    "maximize your roi", "maximise your roi", "grow your business",
    "take your business to the next level",
)

# Mistake #4 — generic pain question: a category question anyone in the space
# could ask. We ONLY flag these generic openers, never all questions (Socivo:
# a specific lived-moment question can outperform a claim).
_GENERIC_PAIN_Q = re.compile(
    r"^\s*(?:struggling with|tired of|sick of|fed up with|looking for|"
    r"do you struggle|are you struggling|are you ready to)\b.*\?",
    re.IGNORECASE,
)


def _check_socivo_rules(headline: str, primary_text: str,
                       description: str) -> List[CopyIssue]:
    """Socivo copy detectors. ADDITIVE, every issue source='socivo'.

    Two high-precision checks from ad-copywriting.md. The fuzzier
    feature-vs-benefit headline check is deliberately omitted — it
    false-positives on Socivo's own contrast/feeling formulas.
    """
    out: List[CopyIssue] = []
    full = " ".join(t for t in (headline, primary_text, description) if t)
    if not full:
        return out
    low = full.lower()

    # Vague outcome language — only when nothing in the copy quantifies it
    # (a number anywhere usually means the claim IS specific).
    if not _has_concrete_numbers(full):
        hits = [p for p in _VAGUE_OUTCOME if p in low]
        if hits:
            quoted = ", ".join(f'"{h}"' for h in hits[:3])
            out.append(CopyIssue(
                severity="info", field="copy", source="socivo",
                message=(f"Vague outcome language: {quoted}. It promises a result "
                         "without saying what changes or by how much — readers tune it out."),
                fix=("Replace with a specific, quantified outcome in the customer's own "
                     "words. Socivo: \"We found seven figures in optimization\" beats "
                     "\"make smarter decisions\". Pull a real number — time saved, % lift, days cut."),
                lift_pct=8,
            ))

    # Generic pain question — check the headline and the first sentence of body.
    first_sentence = ""
    if primary_text:
        first_sentence = re.split(r"(?<=[.!?])\s", primary_text.strip(), maxsplit=1)[0]
    for field_name, text in (("headline", headline), ("primary_text", first_sentence)):
        if text and _GENERIC_PAIN_Q.match(text.strip()):
            out.append(CopyIssue(
                severity="info", field=field_name, source="socivo",
                message=("Generic pain question — a category question anyone in your "
                         "space could ask, so the reader scrolls past instead of feeling seen."),
                fix=("Swap it for a specific moment the buyer has actually lived. Socivo: "
                     "\"Struggling with reporting?\" → \"Your board asked for a forecast. "
                     "How long did it take?\""),
                lift_pct=6,
            ))
            break          # one is enough — don't drown the user

    return out


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

    # --- Text-quality scans (typos / symbols / AI-smells / punctuation /
    # em-dashes). Runs per field so each issue is attributed to the right
    # input slot in the UI.
    platform_id = getattr(fmt, "platform_id", "") or ""
    for field_name, text in (("headline",     headline),
                              ("primary_text", primary_text),
                              ("description",  description)):
        issues.extend(_check_text_quality(text, field_name,
                                           platform_id=platform_id))

    # Socivo ad-copywriting detectors (additive, source="socivo").
    issues.extend(_check_socivo_rules(headline, primary_text, description))

    # Order most important first.
    SEV_ORDER = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: SEV_ORDER.get(i.severity, 3))
    return issues
