"""Directional linguistic read of ad copy — readability, density, reading
time, and persuasion markers.

Pure-Python, ZERO new dependencies (deliberately not textstat): keeps the
Railway worker lean (no OOM / deploy surface) and gives the same user value
for short ad copy. Syllable counting is a vowel-group heuristic — accurate
enough for a DIRECTIONAL readability read, not academic precision. The UI
labels it as such; it is never presented as a measured grade.

Public entry: ``analyze_copy(headline, primary_text, description)`` ->
``LinguisticsRead``.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import List

__all__ = ["LinguisticsRead", "analyze_copy"]


# Persuasion / power-word markers, grouped. A deterministic word-list scan —
# same spirit as copy_critique's lists. High-precision tokens only (common,
# ambiguous words like "how"/"only"/"before" are deliberately excluded so the
# scan reads as signal, not noise). Presence is directional, not a score.
_PERSUASION = {
    "urgency":      ("now", "today", "instant", "instantly", "hurry", "limited",
                     "deadline", "expires", "last chance", "don't miss", "ends soon"),
    "social_proof": ("proven", "trusted", "join", "thousands", "millions",
                     "rated", "bestselling", "recommended", "as seen"),
    "value":        ("free", "save", "guarantee", "guaranteed", "bonus",
                     "discount", "money-back", "half price"),
    "curiosity":    ("secret", "discover", "reveal", "revealed", "mistake",
                     "truth", "surprising"),
    "emotion":      ("imagine", "finally", "effortless", "stress-free",
                     "confidence", "relief"),
    "exclusivity":  ("exclusive", "members", "early access", "vip", "invite only"),
}

# ~200 words/minute — average adult silent reading speed.
_WPM = 200

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_SENTENCE_RE = re.compile(r"[.!?]+")
_VOWEL_GROUPS = re.compile(r"[aeiouy]+")


def _count_syllables(word: str) -> int:
    """Vowel-group heuristic with a silent-trailing-e adjustment.

    Approximate — within ~1 syllable for most English words, which averages
    out well over a few sentences. Not a dictionary lookup by design.
    """
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    count = len(_VOWEL_GROUPS.findall(w))
    # Silent trailing 'e' (but not "-le" as in "table"/"simple").
    if w.endswith("e") and not w.endswith("le") and count > 1:
        count -= 1
    return max(1, count)


def _readability_label(flesch_reading_ease: float) -> str:
    fre = flesch_reading_ease
    if fre >= 80:
        return "very easy"
    if fre >= 70:
        return "easy"
    if fre >= 60:
        return "plain"
    if fre >= 50:
        return "fairly hard"
    if fre >= 30:
        return "hard"
    return "very hard"


@dataclass
class LinguisticsRead:
    word_count: int = 0
    sentence_count: int = 0
    avg_words_per_sentence: float = 0.0
    avg_syllables_per_word: float = 0.0
    flesch_reading_ease: float = 0.0      # 0-100, higher = easier
    grade_level: float = 0.0              # Flesch-Kincaid grade (US school grade)
    readability_label: str = ""
    reading_time_seconds: int = 0
    persuasion_markers: dict = field(default_factory=dict)  # category -> [words]
    persuasion_count: int = 0
    insights: List[str] = field(default_factory=list)       # directional notes
    is_empty: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_copy(headline: str = "", primary_text: str = "",
                  description: str = "") -> LinguisticsRead:
    """Directional readability + persuasion read over the combined copy.

    Returns an empty read (``is_empty=True``) when there's no copy — the
    caller / UI hides the card rather than showing zeros.
    """
    full = " ".join(t.strip() for t in (headline, primary_text, description)
                    if t and t.strip())
    if not full:
        return LinguisticsRead()

    words = _WORD_RE.findall(full)
    word_count = len(words)
    if word_count == 0:
        return LinguisticsRead()

    sentences = [s for s in _SENTENCE_RE.split(full) if s.strip()]
    sentence_count = max(1, len(sentences))

    syllables = sum(_count_syllables(w) for w in words)
    avg_wps = word_count / sentence_count
    avg_spw = syllables / word_count

    # Flesch Reading Ease + Flesch-Kincaid Grade Level (standard formulas).
    fre = 206.835 - 1.015 * avg_wps - 84.6 * avg_spw
    fre = max(0.0, min(100.0, fre))
    # Cap at grade 18 (post-grad). The raw formula can spike absurdly high on a
    # short, all-polysyllabic line; 18 is the practical ceiling of the scale.
    fkgl = max(0.0, min(18.0, 0.39 * avg_wps + 11.8 * avg_spw - 15.59))

    reading_time = max(1, round(word_count / _WPM * 60))

    # Persuasion-marker scan (word-boundary for single tokens, substring for
    # multi-word phrases).
    low = full.lower()
    markers: dict = {}
    total_markers = 0
    for category, tokens in _PERSUASION.items():
        hits = []
        for token in tokens:
            if " " in token:
                if token in low:
                    hits.append(token)
            elif re.search(rf"\b{re.escape(token)}\b", low):
                hits.append(token)
        if hits:
            markers[category] = hits
            total_markers += len(hits)

    # Directional insights — honest, plain-English, only when actionable.
    insights: List[str] = []
    if fkgl >= 12:
        insights.append(
            f"Reads at roughly grade {fkgl:.0f} — dense for a fast feed. "
            "Shorter sentences and simpler words help it land mid-scroll; aim for grade 6-8."
        )
    elif fkgl <= 5:
        insights.append(
            f"Very easy read (~grade {fkgl:.0f}) — well-suited to broad cold reach."
        )
    if avg_wps > 20:
        insights.append(
            f"Sentences average {avg_wps:.0f} words — long for ad copy. "
            "Break them up; punchy fragments tend to outperform full sentences in-feed."
        )
    if total_markers == 0:
        insights.append(
            "No persuasion markers detected — the copy reads as purely descriptive. "
            "One concrete value or curiosity hook can lift click intent."
        )

    return LinguisticsRead(
        word_count=word_count,
        sentence_count=sentence_count,
        avg_words_per_sentence=round(avg_wps, 1),
        avg_syllables_per_word=round(avg_spw, 2),
        flesch_reading_ease=round(fre, 1),
        grade_level=round(fkgl, 1),
        readability_label=_readability_label(fre),
        reading_time_seconds=reading_time,
        persuasion_markers=markers,
        persuasion_count=total_markers,
        insights=insights,
        is_empty=False,
    )
