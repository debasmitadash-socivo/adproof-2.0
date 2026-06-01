"""Platform × ad-format taxonomy with 2026-current benchmark estimates.

Catalogues the advertising surfaces a user can pick from in the wizard --
Meta Facebook & Instagram, Google Search & Display, YouTube, LinkedIn, TikTok
-- and the ad formats inside each, with directional industry benchmark CTRs,
CPMs, CPCs, asset requirements, copy limits, and best-fit guidance.

Data freshness
--------------
Each format carries an ``as_of`` field flagging when those numbers were last
revised. The 2024 baselines come from Wordstream / Meta / LinkedIn / TikTok
public reports; the 2026 deltas reflect documented market shifts:

* Continued iOS privacy + signal loss pushing CPCs and CPMs up across
  conversion-led channels
* AI-generated creative everywhere -> more creative volume, faster fatigue,
  Feed CTR drift down ~5-10%
* Reels / TikTok matured -- CPMs no longer a "cheap reach" loophole
* B2B (LinkedIn) inflated as buying committees harden the funnel
* Search auction more competitive (Performance Max + AI Overviews pushing
  more spend into the same auctions)

These remain ESTIMATES, not measured. Real performance swings 2-5x against
them depending on industry, geo, audience quality, and seasonality. The
in-app "Override benchmark" lets you punch in your own numbers; v1.x adds a
Gemini-grounded "refresh from the web" button that pulls live published
averages at simulate time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "AdFormat",
    "PLATFORMS",
    "FORMATS",
    "BENCHMARK_AS_OF",
    "list_platforms",
    "platform_formats",
    "get_format",
    "platform_name",
]

# Default freshness label for the benchmark numbers below. Each format can
# override via its own `benchmarks["as_of"]` -- e.g. after a Gemini-grounded
# refresh, only that one format gets bumped.
BENCHMARK_AS_OF = "2026-Q1"


# ===========================================================================
# Data class
# ===========================================================================

@dataclass(frozen=True)
class AdFormat:
    """One ad placement / format within a platform."""
    id: str                       # unique key, e.g. "meta_fb_feed_image"
    platform_id: str              # "meta_facebook"
    platform_name: str            # "Meta — Facebook"
    name: str                     # "Feed — Single Image"
    media_type: str               # "image" | "video" | "text" | "carousel"
    asset_types: tuple            # what the creative must supply
    benchmarks: dict              # {"ctr","cpm","cpc","primary_metric",
                                  #  "ctr_range":(lo,hi)}
    copy_limits: dict             # {"headline_chars": 40, ...}
    aspect_ratios: tuple          # ("1:1","4:5","9:16")
    best_for: str                 # short user-facing fit description
    tone: str                     # creative tone guidance (LLM/critique uses)
    primary_objectives: tuple     # ("awareness","consideration","conversion")
    notes: str = ""

    # Map to the simulator's existing channel categories for base-rate anchor.
    @property
    def simulation_channel(self) -> str:
        return _FORMAT_TO_CHANNEL[self.id]


# ===========================================================================
# Platform metadata
# ===========================================================================

PLATFORMS: dict = {
    "meta_facebook": {
        "name": "Meta — Facebook",
        "audience_default": "broad reach, ages 25-65, mixed-intent",
        "strength": "high reach + targeting depth, mid-funnel friendly",
    },
    "meta_instagram": {
        "name": "Meta — Instagram",
        "audience_default": "ages 18-44, visually-led, lifestyle/discovery",
        "strength": "discovery + brand affinity, strong for lifestyle / "
                    "DTC / fashion / beauty",
    },
    "google_search": {
        "name": "Google — Search",
        "audience_default": "high-intent (active searchers)",
        "strength": "captures demand at the moment of intent; the strongest "
                    "channel for conversion-led campaigns",
    },
    "google_display": {
        "name": "Google — Display Network",
        "audience_default": "broad reach across publishers; passive context",
        "strength": "low-cost reach + retargeting; awareness/consideration",
    },
    "youtube": {
        "name": "YouTube",
        "audience_default": "broad reach, video-attentive audiences",
        "strength": "long-form storytelling + brand lift; pairs with Search",
    },
    "linkedin": {
        "name": "LinkedIn",
        "audience_default": "professionals, B2B decision-makers, 25-55",
        "strength": "the dominant B2B channel; high cost but high "
                    "decision-maker density",
    },
    "tiktok": {
        "name": "TikTok",
        "audience_default": "Gen-Z + young millennials, casual / "
                            "entertainment-first",
        "strength": "discovery + virality; high engagement, lower-funnel "
                    "weaker than Meta but improving",
    },
}


def list_platforms() -> list:
    """Return platform ids in display order."""
    return list(PLATFORMS.keys())


def platform_name(platform_id: str) -> str:
    return PLATFORMS.get(platform_id, {}).get("name", platform_id)


# ===========================================================================
# Format catalogue
# ===========================================================================
#
# Every format declares:
#   benchmarks   -- 2024 industry average, with a realistic range
#   asset_types  -- which creative slots the user must fill
#   copy_limits  -- platform-enforced character / element limits
#   tone         -- creative-style guidance used by the critique
#
# Map to the simulator's coarse channel categories (display / social_feed /
# search / video / email) so the existing base-rate anchoring keeps working.
# ===========================================================================

_FORMAT_TO_CHANNEL: dict = {}   # filled below


def _f(**kwargs) -> AdFormat:
    fmt = AdFormat(**kwargs)
    return fmt


FORMATS_RAW: list = [
    # ---------------- Meta Facebook ----------------
    _f(id="meta_fb_feed_image", platform_id="meta_facebook",
       platform_name="Meta — Facebook", name="Feed — Single Image",
       media_type="image",
       asset_types=("image", "primary_text", "headline", "cta", "link"),
       # 2026: CPM up ~18% on 2024 (privacy + AI-creative supply glut bidding
       # the same auctions). CTR drifted down ~5% as static feed loses
       # share-of-attention to Reels.
       benchmarks={"ctr": 0.0085, "cpm": 13.00, "cpc": 1.55,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0042, 0.0175),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0090, "cpm": 11.0},
                   "trend_note": "CPM +18% vs 2024; CTR -5% (Reels share gain)"},
       copy_limits={"primary_text_chars": 125, "headline_chars": 40,
                    "description_chars": 30},
       aspect_ratios=("1:1", "4:5"),
       best_for="direct-response, e-commerce, lead gen",
       tone="benefit-led, concrete offer, scroll-stopping visual",
       primary_objectives=("conversion", "consideration")),
    _f(id="meta_fb_feed_video", platform_id="meta_facebook",
       platform_name="Meta — Facebook", name="In-Feed Video",
       media_type="video",
       asset_types=("video", "primary_text", "headline", "cta", "link"),
       benchmarks={"ctr": 0.0115, "cpm": 14.00, "cpc": 1.22,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0058, 0.0215),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0120, "cpm": 12.0},
                   "trend_note": "CPM +17% vs 2024; CTR -4%"},
       copy_limits={"primary_text_chars": 125, "headline_chars": 40,
                    "video_seconds_max": 240},
       aspect_ratios=("1:1", "4:5", "9:16"),
       best_for="Plays in the main Facebook feed between organic posts. "
                "Any aspect ratio, up to 4 min — best for brand storytelling, "
                "product demos, mid-funnel consideration.",
       tone="hook in first 3 seconds, captions-on by default",
       primary_objectives=("awareness", "consideration", "conversion")),
    _f(id="meta_fb_reels", platform_id="meta_facebook",
       platform_name="Meta — Facebook", name="Reels",
       media_type="video",
       asset_types=("video", "primary_text", "cta", "link"),
       benchmarks={"ctr": 0.0130, "cpm": 9.00, "cpc": 0.72,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0075, 0.0245),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0140, "cpm": 7.0},
                   "trend_note": "Format matured: CPM +29%, CTR -7%. No longer a 'cheap reach' loophole."},
       copy_limits={"primary_text_chars": 72, "video_seconds_max": 90},
       aspect_ratios=("9:16",),
       best_for="Plays in the dedicated Reels feed (vertical scroller, "
                "TikTok-style). Vertical 9:16 only, up to 90s — best for "
                "discovery, Gen-Z / millennial reach, cheaper CPM than Feed.",
       tone="native, vertical, fast-paced; trends + sound matter",
       primary_objectives=("awareness", "consideration")),

    # ---------------- Meta Instagram ----------------
    _f(id="meta_ig_feed_image", platform_id="meta_instagram",
       platform_name="Meta — Instagram", name="Feed — Single Image",
       media_type="image",
       asset_types=("image", "caption", "cta", "link"),
       benchmarks={"ctr": 0.0075, "cpm": 15.00, "cpc": 1.85,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0038, 0.0150),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0080, "cpm": 13.0},
                   "trend_note": "Feed losing time-on-app to Reels; CPM up, CTR down."},
       copy_limits={"caption_chars": 2200},
       aspect_ratios=("1:1", "4:5"),
       best_for="lifestyle / DTC / fashion / beauty; visually-led brands",
       tone="aspirational visual, clean, lifestyle context",
       primary_objectives=("awareness", "consideration", "conversion")),
    _f(id="meta_ig_reels", platform_id="meta_instagram",
       platform_name="Meta — Instagram", name="Reels",
       media_type="video",
       asset_types=("video", "caption", "cta", "link"),
       benchmarks={"ctr": 0.0135, "cpm": 10.00, "cpc": 0.78,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0078, 0.0240),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0140, "cpm": 8.0},
                   "trend_note": "Now ~50% of IG ad inventory; CPM up 25%."},
       copy_limits={"caption_chars": 2200, "video_seconds_max": 90},
       aspect_ratios=("9:16",),
       best_for="Plays in the dedicated Reels tab (vertical scroller). "
                "Vertical 9:16 only, up to 90s — best for Gen-Z / millennial "
                "discovery and viral upside.",
       tone="native, trend-aware, short hook",
       primary_objectives=("awareness", "consideration")),
    _f(id="meta_ig_stories", platform_id="meta_instagram",
       platform_name="Meta — Instagram", name="Stories",
       media_type="video",
       asset_types=("image_or_video", "cta", "link"),
       benchmarks={"ctr": 0.0065, "cpm": 11.00, "cpc": 1.58,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0032, 0.0135),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0070, "cpm": 9.0},
                   "trend_note": "Stories engagement plateauing; budgets reallocating to Reels."},
       copy_limits={"video_seconds_max": 60},
       aspect_ratios=("9:16",),
       best_for="Plays full-screen at the top of the IG/FB app between "
                "friends' Stories. Vertical 9:16, up to 60s — best for "
                "time-sensitive offers and retargeting.",
       tone="full-screen, fast, swipe-up clear",
       primary_objectives=("consideration", "conversion")),

    # ---------------- Google Search ----------------
    _f(id="google_search_rsa", platform_id="google_search",
       platform_name="Google — Search", name="Responsive Search Ad",
       media_type="text",
       asset_types=("headline_1", "headline_2", "headline_3",
                    "description_1", "description_2", "final_url"),
       benchmarks={"ctr": 0.0350, "cpm": 0.0, "cpc": 3.20,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0160, 0.0640),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0320, "cpc": 2.70},
                   "trend_note": "AI Overviews + Performance Max compressed organic real estate; CPC +19%, CTR +9% from better Gemini-powered ad matching."},
       copy_limits={"headline_chars": 30, "description_chars": 90,
                    "min_headlines": 3, "min_descriptions": 2},
       aspect_ratios=(),
       best_for="high-intent capture; the strongest direct-response channel",
       tone="match the searcher's query; lead with the benefit/answer",
       primary_objectives=("conversion",),
       notes="cost is per-click; CPM is not applicable"),

    # ---------------- Google Display ----------------
    _f(id="google_display_responsive", platform_id="google_display",
       platform_name="Google — Display", name="Responsive Display Ad",
       media_type="image",
       asset_types=("image_landscape", "image_square", "logo",
                    "headline", "long_headline", "description"),
       benchmarks={"ctr": 0.0042, "cpm": 3.80, "cpc": 0.82,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0018, 0.0085),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0046, "cpm": 3.10},
                   "trend_note": "Banner-blindness deeper post-AI-image saturation; CTR -9%."},
       copy_limits={"headline_chars": 30, "long_headline_chars": 90,
                    "description_chars": 90},
       aspect_ratios=("1.91:1", "1:1"),
       best_for="awareness + retargeting at low CPM",
       tone="simple, single message, brand-recognisable",
       primary_objectives=("awareness", "consideration")),

    # ---------------- YouTube ----------------
    _f(id="youtube_instream_skippable", platform_id="youtube",
       platform_name="YouTube", name="In-Stream Skippable",
       media_type="video",
       asset_types=("video", "headline", "description", "cta", "link"),
       benchmarks={"ctr": 0.0085, "cpm": 11.50, "cpc": 0.14,
                   "primary_metric": "vtr",
                   "ctr_range": (0.0042, 0.0170),
                   "vtr": 0.27,
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0080, "cpm": 9.70, "vtr": 0.25},
                   "trend_note": "Shorts pulling shorter attention back to long-form; CPM +19%."},
       copy_limits={"video_seconds_max": 360,
                    "headline_chars": 15, "description_chars": 90},
       aspect_ratios=("16:9",),
       best_for="brand lift + storytelling; pairs with Search",
       tone="hook in first 5 seconds before the skip; brand early",
       primary_objectives=("awareness", "consideration")),
    _f(id="youtube_bumper", platform_id="youtube",
       platform_name="YouTube", name="Bumper (6s)",
       media_type="video",
       asset_types=("video", "cta", "link"),
       benchmarks={"ctr": 0.0055, "cpm": 6.50, "cpc": None,
                   "primary_metric": "reach",
                   "ctr_range": (0.0018, 0.0115),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0060, "cpm": 5.50},
                   "trend_note": "Brand-recall workhorse; CPM creep from auction pressure."},
       copy_limits={"video_seconds_max": 6, "video_seconds_min": 6},
       aspect_ratios=("16:9",),
       best_for="frequency builder; cheap reach for brand recall",
       tone="one idea, one image; logo + tagline",
       primary_objectives=("awareness",)),

    # ---------------- LinkedIn ----------------
    _f(id="linkedin_sponsored_image", platform_id="linkedin",
       platform_name="LinkedIn", name="Sponsored Content — Single Image",
       media_type="image",
       asset_types=("image", "intro_text", "headline", "cta", "link"),
       benchmarks={"ctr": 0.0045, "cpm": 34.00, "cpc": 6.20,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0022, 0.0100),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0040, "cpm": 30.0, "cpc": 5.50},
                   "trend_note": "B2B inflation: CPM +13%, CPC +13% as buying committees harden funnel."},
       copy_limits={"intro_text_chars": 600, "headline_chars": 200},
       aspect_ratios=("1.91:1", "1:1"),
       best_for="B2B lead gen, decision-maker reach",
       tone="professional, value-led, no consumer-y exclamation marks",
       primary_objectives=("consideration", "conversion")),
    _f(id="linkedin_sponsored_video", platform_id="linkedin",
       platform_name="LinkedIn", name="Sponsored Content — Video",
       media_type="video",
       asset_types=("video", "intro_text", "headline", "cta", "link"),
       benchmarks={"ctr": 0.0065, "cpm": 39.00, "cpc": 6.60,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0032, 0.0130),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0060, "cpm": 35.0},
                   "trend_note": "Best-converting LinkedIn unit; CPM +11%."},
       copy_limits={"intro_text_chars": 600,
                    "video_seconds_max": 600},
       aspect_ratios=("1:1", "16:9"),
       best_for="B2B thought leadership, product demos",
       tone="professional, expert voice, captions-on",
       primary_objectives=("awareness", "consideration")),
    _f(id="linkedin_message", platform_id="linkedin",
       platform_name="LinkedIn", name="Sponsored Messaging",
       media_type="text",
       asset_types=("subject", "message_body", "cta", "link"),
       benchmarks={"ctr": 0.0250, "cpm": 0.0, "cpc": 0.60,
                   "primary_metric": "open_rate",
                   "ctr_range": (0.0120, 0.0440),
                   "open_rate": 0.25,
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0300, "open_rate": 0.30},
                   "trend_note": "Open rates dropped ~5pts due to inbox saturation + spam filtering."},
       copy_limits={"subject_chars": 60, "body_chars": 1500},
       aspect_ratios=(),
       best_for="warm B2B outreach, event invites, gated assets",
       tone="personal, conversational, addressed by name",
       primary_objectives=("consideration", "conversion"),
       notes="charged per send; open + click rates matter more than CPM"),

    # ---------------- TikTok ----------------
    _f(id="tiktok_infeed", platform_id="tiktok",
       platform_name="TikTok", name="In-Feed Ad",
       media_type="video",
       asset_types=("video", "caption", "cta", "link"),
       benchmarks={"ctr": 0.0120, "cpm": 11.00, "cpc": 0.92,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0058, 0.0235),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0100, "cpm": 10.0},
                   "trend_note": "Lower-funnel meaningfully improving with Shop integrations; CTR +20%."},
       copy_limits={"caption_chars": 100, "video_seconds_max": 60},
       aspect_ratios=("9:16",),
       best_for="Gen-Z discovery; conversion now competitive with Meta",
       tone="native, casual, looks like organic content; sound-on",
       primary_objectives=("awareness", "consideration", "conversion")),
    _f(id="tiktok_spark", platform_id="tiktok",
       platform_name="TikTok", name="Spark Ad (boosted organic)",
       media_type="video",
       asset_types=("organic_post_url", "cta"),
       benchmarks={"ctr": 0.0165, "cpm": 10.00, "cpc": 0.68,
                   "primary_metric": "ctr",
                   "ctr_range": (0.0078, 0.0270),
                   "as_of": "2026-Q1",
                   "source_2024": {"ctr": 0.0150, "cpm": 9.0},
                   "trend_note": "Still outperforms made-for-ad video; creator economy maturing."},
       copy_limits={},
       aspect_ratios=("9:16",),
       best_for="creator/UGC amplification; outperforms made-for-ad video",
       tone="authentic creator voice, not branded",
       primary_objectives=("awareness", "consideration")),
]


# Build the lookup + the format -> simulator-channel map.
FORMATS: dict = {fmt.id: fmt for fmt in FORMATS_RAW}

_FORMAT_TO_CHANNEL.update({
    "meta_fb_feed_image": "social_feed",
    "meta_fb_feed_video": "social_feed",
    "meta_fb_reels": "video",
    "meta_ig_feed_image": "social_feed",
    "meta_ig_reels": "video",
    "meta_ig_stories": "video",
    "google_search_rsa": "search",
    "google_display_responsive": "display",
    "youtube_instream_skippable": "video",
    "youtube_bumper": "video",
    "linkedin_sponsored_image": "social_feed",
    "linkedin_sponsored_video": "social_feed",
    "linkedin_message": "email",
    "tiktok_infeed": "video",
    "tiktok_spark": "video",
})


def platform_formats(platform_id: str) -> list:
    """List formats available within a platform, preserving display order."""
    return [f for f in FORMATS_RAW if f.platform_id == platform_id]


def get_format(format_id: str) -> AdFormat:
    if format_id not in FORMATS:
        raise KeyError(f"Unknown ad format '{format_id}'. "
                       f"Available: {sorted(FORMATS)}")
    return FORMATS[format_id]
