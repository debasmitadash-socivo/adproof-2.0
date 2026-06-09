"""Type- and objective-aware advice for a scored creative.

Pillar B (Phase B half-2): once the vision pass has tagged a creative
as e.g. ``talking_head`` + ``consideration``, this module emits 2-3
actionable suggestions that are concretely RIGHT for that combination.

The advice is intentionally hand-authored (not LLM-generated) for three
reasons:
1. Determinism — the same creative always gets the same advice, no
   non-deterministic Gemini slop polluting the report.
2. Cost — zero Gemini tokens spent for this layer.
3. Quality — a senior performance marketer's notes encoded as data, so
   we ship rules we actually believe in.

If a (type, objective) combination isn't in the matrix the function
returns a small set of generic-but-still-useful suggestions for that
TYPE alone — better than silence, and still honest.

Public entry point: ``advice_for(creative_type, objective)``.
"""
from __future__ import annotations

__all__ = ["advice_for", "type_label"]


# Human-readable label per slug. Mirrors the taxonomy in
# visual_analysis._RESPONSE_SHAPE so the report and the prompt stay in sync.
_TYPE_LABEL = {
    "product_shot":    "Product shot",
    "lifestyle":       "Lifestyle image",
    "text_heavy":      "Text-heavy graphic",
    "ugc":             "UGC-style",
    "illustration":    "Illustration",
    "screenshot":      "Screenshot",
    "meme":            "Meme",
    "talking_head":    "Talking head",
    "broll":           "B-roll",
    "motion_graphic":  "Motion graphic",
    "product_demo":    "Product demo",
    "before_after":    "Before-and-after",
    "animated":        "Animated",
}


def type_label(slug: str) -> str:
    """Pretty label for a creative-type slug."""
    return _TYPE_LABEL.get((slug or "").lower(), (slug or "").replace("_", " ").title())


# (type, objective) → list of suggestions. Empty (type,) entry is the
# fallback advice when we know the type but not a tuned combination.
_ADVICE: dict = {
    # --- IMAGE TYPES ----------------------------------------------------
    ("product_shot", "awareness"): [
        "Awareness ads on hero product shots usually under-deliver — your image is doing the brand work, but it's not stopping the scroll. Add a bold visual element (oversized text, gradient, motion blur) so it cuts through.",
        "Crop tighter on the product — a wider crop reads as 'catalogue', a tighter one as 'editorial'. Editorial wins on Reels / IG awareness.",
        "Keep the brand mark visible in the first 30% of the canvas — unbranded awareness ads waste reach.",
    ],
    ("product_shot", "consideration"): [
        "Pair the product shot with a 1-line benefit overlay — e.g. '3-min skincare, sweat-proof.' Bare product shots score low on relevance-of-value-prop for consideration briefs.",
        "If the product has multiple SKUs, show ONE — choice paralysis kills CTR.",
        "Add a clear CTA chip in the lower-right (e.g. 'Try free') — improves CTR ~10–15% on average across DTC tests.",
    ],
    ("product_shot", "conversion"): [
        "Lead with price or a deal sticker — conversion-objective ads with a visible price clear break-even faster.",
        "Show the product in-context with a person or hand for scale; pure cut-outs feel like catalogue and convert worse.",
        "Match the on-image colour palette to the landing page — coherence between ad and LP lifts conversion rate ~8%.",
    ],
    ("lifestyle", "awareness"): [
        "Lifestyle imagery is strong for awareness — keep the brand subtle but unmissable; treat the image as a mood, not a product ad.",
        "Use a single hero face / human focal point if possible — it doubles attention vs object-only lifestyle.",
        "Skip on-image copy entirely on awareness lifestyle — let the image breathe.",
    ],
    ("lifestyle", "consideration"): [
        "Lifestyle is great at vibe, weak at the click. Add a one-line bold-text overlay tying the moment to the offer (e.g. '90-second meals') — this converts the mood into intent.",
        "Show outcome, not feature — a lifestyle image of 'after using the product' beats 'while using the product' on consideration CTR.",
        "Pair with copy that names the audience explicitly ('For brides-to-be / first-time runners…') — relevance bump.",
    ],
    ("lifestyle", "conversion"): [
        "Lifestyle ALONE rarely converts — the maths needs a price or proof point. Add a discount badge, review quote, or 'as seen in…' strip.",
        "Cut to a tighter framing — full-scene lifestyle feels editorial; tight-frame feels 'available now'.",
        "Add scarcity / urgency to the copy if honest ('48 hours left', not invented).",
    ],
    ("text_heavy", "awareness"): [
        "Text-heavy = informational, weakest format for awareness. If you must run it, drop ≥40% of the words and make ONE phrase the hero.",
        "Use a contrast colour pair (one for the hero phrase, one for context) — flat text reads as a slide, not an ad.",
        "Consider remixing as a 6s video bumper — text-heavy stills are usually re-cuttable as motion.",
    ],
    ("text_heavy", "consideration"): [
        "Text-heavy works for consideration ONLY if the hero phrase reads in <2 seconds at thumb-stop scale. Test on your phone at arm's length.",
        "Add ONE supporting image element (icon, illustration, product cutout) — pure text underperforms pure-image by ~30% on CTR even when the copy is good.",
        "Lead with a question if the hero phrase isn't a benefit — questions outperform claims for consideration ads.",
    ],
    ("text_heavy", "conversion"): [
        "Add a clear offer line (price / discount / outcome) — text-heavy without a numeric offer rarely clears break-even.",
        "Use a clear visual hierarchy: hook (largest) → benefit → CTA — don't lay out the copy as a paragraph.",
        "Make the CTA a coloured button shape, not just text — buttons clear visual-clarity scoring much higher.",
    ],
    ("ugc", "awareness"): [
        "UGC is overrated for awareness — algorithms can't tell it from organic, so reach can be cheap, but brand recall is weak. Make sure the brand mark or product name appears in the first frame.",
        "Hand-held / off-axis framing reads native — keep it.",
        "Captions on a black bar at top help the muted-feed problem.",
    ],
    ("ugc", "consideration"): [
        "Strong format for consideration — the conversational tone bypasses ad-blindness. Make sure the hook line is in the FIRST 1.5 seconds.",
        "Show the speaker's face within the first 2s — UGC without a face mid-frame scores lower on attention.",
        "Use the speaker's natural language for the CTA — 'check the link' beats 'visit now' for UGC.",
    ],
    ("ugc", "conversion"): [
        "Add an on-screen price / outcome chip — UGC's authenticity converts only when it points at a concrete claim.",
        "Show the product being used, not just held / mentioned — usage moments are the conversion driver.",
        "Lower the production polish if it's currently too clean — over-produced UGC kills conversion intent.",
    ],
    ("illustration", "awareness"): [
        "Illustration is great for awareness because it stops the scroll — keep the palette bold and the composition simple.",
        "Avoid dense detail; an awareness illustration should read at a glance.",
        "If your brand has a mascot, lead with it — mascots disproportionately drive brand recall.",
    ],
    ("illustration", "consideration"): [
        "Pair the illustration with one short text line — illustrations alone are too symbolic to drive a click.",
        "Use the illustration to externalise the PROBLEM, not the product — 'tired-eyes' illustration > 'caffeine cup' illustration for an energy brand.",
        "Animate one element if possible — a static illustration with one moving accent has ~25% better stopping power.",
    ],
    ("illustration", "conversion"): [
        "Illustrations rarely close conversions on their own — add a numerical proof point (price, %, testimonial number).",
        "Push toward semi-realistic style if currently flat-vector — flat-vector underconverts vs warmer illustration on most product categories.",
    ],
    ("screenshot", "awareness"): [
        "Raw screenshots are weak for awareness — they read as documentation, not invitation. Add a phone or screen frame, plus a one-line context overlay.",
        "Highlight ONE feature with a circle or arrow; full-screen screenshots dilute attention.",
    ],
    ("screenshot", "consideration"): [
        "Screenshot ads work for consideration if the hook is in the on-screen content (e.g. a real chart). Make sure the chart's headline is legible at thumb scale.",
        "Crop tighter on the part you want them to notice — full-app screenshots are noisy.",
    ],
    ("screenshot", "conversion"): [
        "Strong for conversion when the screenshot shows the outcome the buyer wants — e.g. a dashboard with the metric improved, not the product UI.",
        "Add a banner with the CTA (e.g. 'Try free for 14 days') — bare screenshots underperform conversion-objective benchmarks.",
    ],
    ("meme", "awareness"): [
        "Memes are huge for awareness — but only if the joke lands in <1s. Test the format with a friend who doesn't know your brand.",
        "Brand SUBTLY — a watermark or in-image product reference, not a logo bar.",
    ],
    ("meme", "consideration"): [
        "Memes that survive the consideration step add a SECOND beat after the joke — make sure the 'so what' is visible in the image.",
    ],
    ("meme", "conversion"): [
        "Memes rarely convert directly — usually need to point at landing-page content that continues the bit. If you can't, the meme is wasted spend.",
    ],

    # --- VIDEO TYPES ----------------------------------------------------
    ("talking_head", "awareness"): [
        "Talking-head awareness ads are weak — algorithms favour them, but viewers without context skip. Make sure the first 2s contain the brand name spoken OR shown.",
        "Captions are non-negotiable on talking-head awareness — most impressions are muted.",
        "Lead with the speaker's emotion (laugh, surprise, intensity) — not a polite greeting.",
    ],
    ("talking_head", "consideration"): [
        "Talking head is the strongest format for consideration when the script is right. The hook is everything — first 3 seconds must NAME the problem, not introduce the speaker.",
        "Bad hook: 'Hi, I'm Sarah and today I want to talk about…' → kills CTR. Good hook: 'If you're stuck on X, this is for you.' (Use the Script Critic below for a rewrite.)",
        "Cut on every breath — talking-head ads that hold one frame for >3s lose retention sharply.",
    ],
    ("talking_head", "conversion"): [
        "Talking-head converts when the speaker shows the product working OR shares a number (e.g. '£40/day in savings'). Without that, no maths.",
        "End the clip with a clear spoken CTA AND an on-screen one — speech + text dual-encoded CTAs convert ~20% better.",
        "Avoid full-frame speaker for the closing 2 seconds — cut to the product / offer instead.",
    ],
    ("broll", "awareness"): [
        "B-roll on awareness needs a clear central subject — multiple scenes per second lose viewers fast. Stick to 3–4 cuts max in the first 10s.",
        "Add a mood-defining track — silent b-roll in a muted feed is wallpaper.",
        "Open on a face if possible — even b-roll benefits from a 0.5s human anchor before going abstract.",
    ],
    ("broll", "consideration"): [
        "B-roll without an on-screen text hook is a wasted consideration spend — most viewers won't infer the offer from imagery alone. Lay a one-line text hook over the first 2 seconds.",
        "Don't let the music tell the whole story — overlay 2–3 key claims as text on the b-roll.",
        "End with a freeze frame + CTA — b-roll without a clear close converts the click into a swipe.",
    ],
    ("broll", "conversion"): [
        "B-roll usually under-converts vs talking head or product demo — if conversion is the goal, consider re-cutting WITH a voiceover or talking-head intercut.",
        "Layer a price or discount on every shot — silent b-roll's only conversion driver is repetition of the offer.",
    ],
    ("motion_graphic", "awareness"): [
        "Motion graphics excel at awareness — they stop the scroll because feeds expect photography. Keep the colour palette to 2 dominant colours.",
        "Open on text or shape MOTION, not a static frame — even 200ms of static at the start kills retention.",
    ],
    ("motion_graphic", "consideration"): [
        "Motion-graphic consideration needs ONE clear value prop animated big — 'Save £40/month' as growing text wins. Don't pack 4 stats.",
        "Use the motion to DIRECT the eye to the CTA at the end — animated arrows beat static CTA chips.",
    ],
    ("motion_graphic", "conversion"): [
        "Motion graphics rarely close conversions alone — pair with a screenshot of the actual product / outcome at the end.",
        "Animate the price reveal — a number that 'falls in' beats a static price by ~15% on conversion.",
    ],
    ("product_demo", "awareness"): [
        "Product demos are wasted on awareness — buyers don't yet care HOW it works. Cut a 6s teaser that only shows the WOW moment.",
    ],
    ("product_demo", "consideration"): [
        "Strong for consideration. Lead with the OUTCOME of the demo, not the setup. ('Watch what happens when…' beats 'Today I'll show you…')",
        "Speed up any prep / waiting steps to 2x — full-pace demos lose 50% of viewers in 5 seconds.",
        "End on the result + CTA, not on the speaker.",
    ],
    ("product_demo", "conversion"): [
        "Demos are the highest-converting video format when done well. Open with the OUTCOME (final state), then go back and show how — reverse storytelling lifts conversion ~30%.",
        "Show a real person using it — animated/cgi demos convert lower because viewers doubt the result.",
        "Add a price + 'try free' chip in the corner from second 1.",
    ],
    ("before_after", "awareness"): [
        "Before/after is policy-risky on awareness — Meta increasingly bans this format. Verify the platform's current policy for your category before scaling.",
    ],
    ("before_after", "consideration"): [
        "Before/after wins consideration when the 'after' is unambiguous in 1 second. If a viewer can't tell at thumb scale, recut.",
        "Make sure the framing is identical between before and after — different lighting / angle reads as fake and kills CTR.",
    ],
    ("before_after", "conversion"): [
        "Before/after is the highest-converting consumer format — but ONLY when claims are demonstrably true. Add testimonial or proof point text overlay.",
        "Show a TIME stamp ('Day 1 → Day 30') — quantified before/after converts ~2x non-quantified.",
    ],
    ("animated", "awareness"): [
        "Pure animation works for awareness in B2B and tech — keep the brand integrated, not bolted on at the end.",
    ],
    ("animated", "consideration"): [
        "Animated consideration: lead with the PAIN, then the solution. Most animated ads spend too long on cute intros.",
        "Cap at 30s — animation viewers drop off harder than live-action.",
    ],
    ("animated", "conversion"): [
        "Animation is the weakest video format for conversion — viewers discount animated claims. Either add a live-action endorsement OR pivot to a different format.",
    ],
}


def advice_for(creative_type: str, objective: str) -> list[str]:
    """Return 2-3 specific suggestions for a (type, objective) pair.

    Falls back to a small set of type-only suggestions when the exact
    combination isn't in the matrix. Empty when the type isn't known —
    the UI hides the card so the user doesn't see a bare panel.
    """
    t = (creative_type or "").lower().strip()
    obj = (objective or "conversion").lower().strip()
    direct = _ADVICE.get((t, obj))
    if direct:
        return direct
    # Type-only fallback: take advice from the type's most-populated objective.
    for fallback_obj in ("consideration", "conversion", "awareness"):
        alt = _ADVICE.get((t, fallback_obj))
        if alt:
            return [f"({fallback_obj} guidance — adapt for your {obj} brief)"] + alt
    return []
