"""Match a free-text audience description to a synthetic persona segment.

LLM-driven when a key is available; heuristic keyword matching otherwise.
Returns the best-fit segment id, a confidence score, and a one-line rationale
the UI can display ("We mapped your audience to: millennials -- because you
mentioned 'urban professionals 30-40'").
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.llm import extract_json, text_complete
    from src.personas import AUDIENCE_SEGMENTS
except ImportError:
    from llm import extract_json, text_complete
    from personas import AUDIENCE_SEGMENTS

__all__ = ["AudienceMatch", "match_audience"]


@dataclass
class AudienceMatch:
    segment: str                  # id used by personas.filter_personas
    confidence: float             # 0-1
    rationale: str                # short user-facing one-liner
    secondary_segments: list      # additional good-fit ids
    source: str = "heuristic"     # "llm" | "heuristic"

    def to_dict(self) -> dict:
        return {
            "segment": self.segment,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "secondary_segments": list(self.secondary_segments),
            "source": self.source,
        }


_VALID_SEGMENTS = set(AUDIENCE_SEGMENTS.keys())

_LLM_SYSTEM = (
    "You are an audience strategist mapping a free-text target-customer "
    "description onto a fixed catalogue of synthetic audience segments. "
    "Return JSON only."
)

_LLM_TEMPLATE = """\
Target customer description:
\"\"\"{desc}\"\"\"

Choose the best-fit segment from this fixed list, with a confidence 0-1
and a one-line rationale. Allowed segments and what they mean:

  - all                  : no targeting (mixed audience)
  - gen_z                : ages 18-27, digital-first, discovery-led
  - millennials          : ages 28-43, established consumers
  - gen_x                : ages 44-59
  - boomers              : ages 60+
  - high_income          : household income >= $90k
  - budget_conscious     : price-sensitive shoppers
  - early_adopters       : high openness, novelty-seeking
  - socially_influenced  : high susceptibility to social proof

Return ONLY this JSON object:
{{
  "segment": "<one segment id from the list>",
  "confidence": <0-1 float>,
  "rationale": "<one sentence explaining the match>",
  "secondary_segments": [<up to 2 alternative ids>]
}}"""


def _match_via_llm(description: str) -> AudienceMatch | None:
    text = text_complete(_LLM_TEMPLATE.format(desc=description.strip()),
                          system=_LLM_SYSTEM, max_tokens=300, json_mode=True)
    parsed = extract_json(text)
    if not parsed:
        return None
    seg = str(parsed.get("segment", "")).strip().lower()
    if seg not in _VALID_SEGMENTS:
        return None
    try:
        conf = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    secondary = [s for s in parsed.get("secondary_segments", [])
                 if isinstance(s, str) and s in _VALID_SEGMENTS][:2]
    return AudienceMatch(
        segment=seg, confidence=max(0.0, min(1.0, conf)),
        rationale=str(parsed.get("rationale", "")).strip(),
        secondary_segments=secondary, source="llm",
    )


# ---------------------------------------------------------------------------
# Heuristic fallback -- keyword scoring against each segment
# ---------------------------------------------------------------------------

_SEGMENT_KEYWORDS = {
    "gen_z": ["gen z", "gen-z", "teen", "18-25", "18-27", "young adult",
              "tiktok", "college", "student"],
    "millennials": ["millennial", "25-40", "28-43", "30s", "young profession",
                    "new parent", "urban professional"],
    "gen_x": ["gen x", "gen-x", "40s", "50s", "parent of teen", "44-59"],
    "boomers": ["boomer", "60", "65", "retiree", "retired", "senior"],
    "high_income": ["high income", "high net worth", "affluent", "wealthy",
                     "luxury buyer", "premium customer", "$100k", "$150k"],
    "budget_conscious": ["budget", "value-seek", "deal", "discount", "frugal",
                          "price sensitive", "students"],
    "early_adopters": ["early adopter", "tech-forward", "innovator", "first to",
                        "novelty", "trend"],
    "socially_influenced": ["influencer-driven", "social proof", "follows",
                              "fomo", "word of mouth", "community"],
}


def _match_heuristic(description: str) -> AudienceMatch:
    desc = (description or "").lower().strip()
    if not desc:
        return AudienceMatch(segment="all", confidence=0.0,
                              rationale="No description provided -- "
                                        "defaulting to the full audience.",
                              secondary_segments=[], source="heuristic")
    scores: dict = {}
    for seg, words in _SEGMENT_KEYWORDS.items():
        scores[seg] = sum(1 for w in words if w in desc)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_hits = ranked[0]
    if top_hits == 0:
        return AudienceMatch(segment="all", confidence=0.2,
                              rationale="Audience description didn't match a "
                                        "specific segment -- using the full "
                                        "audience.",
                              secondary_segments=[], source="heuristic")
    secondaries = [s for s, h in ranked[1:3] if h > 0]
    total = sum(s for _, s in ranked) or 1
    return AudienceMatch(
        segment=top, confidence=round(top_hits / max(total, 1) * 0.8 + 0.2, 2),
        rationale=f"Matched '{top}' on {top_hits} keyword cue"
                  f"{'s' if top_hits != 1 else ''} in the description.",
        secondary_segments=secondaries, source="heuristic",
    )


def match_audience(description: str, prefer_llm: bool = True) -> AudienceMatch:
    """Return the best-fit synthetic segment for the given description."""
    if prefer_llm:
        m = _match_via_llm(description)
        if m is not None:
            return m
    return _match_heuristic(description)
