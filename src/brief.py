"""Campaign brief container + format validation.

The brief glues the company profile, audience match, and platform/format
selection together for the simulation. ``validate_creative`` checks the user's
uploaded assets against the format's requirements (e.g. video required, copy
under the headline limit) and returns actionable issues for the UI.
"""
from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.platforms import AdFormat, get_format
except ImportError:
    from platforms import AdFormat, get_format

__all__ = ["CampaignBrief", "validate_creative"]

_VALID_OBJECTIVES = ("awareness", "consideration", "conversion")


@dataclass
class CampaignBrief:
    objective: str = "consideration"     # awareness | consideration | conversion
    platform_id: str = "meta_facebook"
    format_id: str = "meta_fb_feed_image"
    budget: float = 10_000.0
    days: int = 14
    daily_reach: float = 0.35
    n_runs: int = 20
    # Optional explicit benchmark anchors (None = derive from format).
    target_ctr_override: float | None = None
    target_conversion_rate: float | None = 0.025
    # --- Real economics (supplied by the advertiser; the honest inputs) ----
    # Average order value / customer value in `currency`. When set, this is
    # used DIRECTLY for revenue = conversions × avg_order_value — no synthetic
    # guessing. This is what makes the $5-toy vs £50k-course distinction real.
    avg_order_value: float | None = None
    product_price: float | None = None     # optional, for display/context
    currency: str = "GBP"                  # AdProof is UK-based → £ default
    # Target market for this campaign. Drives per-geo benchmark grounding,
    # currency, and the cultural/regulatory lens in LLM prompts.
    geo: str = "UK"

    def __post_init__(self):
        if self.objective not in _VALID_OBJECTIVES:
            self.objective = "consideration"
        self.budget = float(max(self.budget, 100.0))
        self.days = int(max(self.days, 1))
        self.daily_reach = float(min(max(self.daily_reach, 0.05), 1.0))
        self.n_runs = int(max(self.n_runs, 5))
        if self.avg_order_value is not None:
            self.avg_order_value = float(max(self.avg_order_value, 0.0)) or None
        self.currency = (self.currency or "GBP").upper()
        self.geo = (self.geo or "UK").strip() or "UK"

    @property
    def format(self) -> AdFormat:
        return get_format(self.format_id)

    @property
    def effective_target_ctr(self) -> float:
        """The CTR to anchor the simulation to."""
        if self.target_ctr_override and self.target_ctr_override > 0:
            return self.target_ctr_override
        return float(self.format.benchmarks.get("ctr", 0.012))

    @property
    def effective_cpm(self) -> float:
        cpm = float(self.format.benchmarks.get("cpm", 10.0))
        # For CPC-priced formats (CPM == 0), approximate equivalent CPM via
        # CTR * CPC * 1000 so budget -> impressions math still works.
        if cpm <= 0:
            cpc = self.format.benchmarks.get("cpc") or 1.0
            ctr = self.format.benchmarks.get("ctr") or 0.01
            cpm = ctr * cpc * 1000
        return cpm

    def to_dict(self) -> dict:
        return asdict(self)


# ===========================================================================
# Creative validation against the chosen format
# ===========================================================================

@dataclass
class CreativeAssets:
    image_path: str | None = None
    video_path: str | None = None
    headline: str = ""
    primary_text: str = ""
    description: str = ""
    cta: str = ""
    link: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def validate_creative(brief: CampaignBrief,
                      assets: CreativeAssets) -> list:
    """Return a list of validation issues, each a dict {severity, message}.

    Severity is 'error' (blocks the simulation), 'warning' (soft), or 'info'.
    """
    fmt = brief.format
    issues: list = []

    media = fmt.media_type
    if media == "image" and not assets.image_path:
        issues.append({"severity": "error",
                        "message": f"{fmt.name} requires an image asset."})
    if media == "video" and not (assets.video_path or assets.image_path):
        # We accept an image as a stand-in (e.g. video thumbnail) but warn.
        issues.append({"severity": "warning",
                        "message": f"{fmt.name} is a video format. Upload a "
                                   "video file for the most accurate scoring; "
                                   "an image will be treated as a still."})
    if media == "text" and not (assets.headline or assets.primary_text):
        issues.append({"severity": "error",
                        "message": f"{fmt.name} requires written copy."})

    limits = fmt.copy_limits
    if "headline_chars" in limits and assets.headline:
        if len(assets.headline) > limits["headline_chars"]:
            issues.append({"severity": "warning",
                            "message": f"Headline is {len(assets.headline)} "
                                       f"chars; {fmt.name} allows "
                                       f"{limits['headline_chars']}."})
    if "primary_text_chars" in limits and assets.primary_text:
        if len(assets.primary_text) > limits["primary_text_chars"]:
            issues.append({"severity": "warning",
                            "message": f"Primary text is "
                                       f"{len(assets.primary_text)} chars; "
                                       f"{fmt.name} truncates at "
                                       f"{limits['primary_text_chars']}."})
    if "description_chars" in limits and assets.description:
        if len(assets.description) > limits["description_chars"]:
            issues.append({"severity": "warning",
                            "message": "Description over the format limit "
                                       f"({limits['description_chars']})."})

    if "link" in fmt.asset_types and not assets.link:
        issues.append({"severity": "info",
                        "message": "Add a destination URL to score "
                                   "click-through conversion accurately."})

    return issues
