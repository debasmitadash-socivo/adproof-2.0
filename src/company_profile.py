"""Parse a free-text company description into a structured profile.

Uses Claude / GPT-4o when an API key is available; falls back to a deterministic
keyword-based heuristic so the wizard always produces a profile.
"""
from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.llm import extract_json, text_complete
except ImportError:                                  # `python src/...`
    from llm import extract_json, text_complete

__all__ = ["CompanyProfile", "parse_company"]


# ---------------------------------------------------------------------------
# Structured profile produced by parsing
# ---------------------------------------------------------------------------

@dataclass
class CompanyProfile:
    raw_description: str
    company_name: str = ""
    industry: str = ""               # e.g. "DTC beauty"
    business_model: str = "b2c"      # b2c | b2b | marketplace | dtc | saas
    product_category: str = "general"  # maps onto persona categories
    value_proposition: str = ""
    target_customer_summary: str = ""
    price_position: str = "mid"      # value | mid | premium | luxury
    brand_tone: str = "neutral"      # bold | friendly | premium | technical
    source: str = "heuristic"        # "llm" or "heuristic"

    def to_dict(self) -> dict:
        return asdict(self)

    def short_summary(self) -> str:
        bits = []
        if self.company_name:
            bits.append(f"**{self.company_name}**")
        bits.append(self.industry or "(industry unspecified)")
        bits.append(self.business_model.upper())
        if self.product_category and self.product_category != "general":
            bits.append(f"category: {self.product_category}")
        if self.price_position:
            bits.append(f"{self.price_position}-priced")
        return " · ".join(bits)


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You are a senior marketing strategist parsing a company description "
    "into a structured profile. Be specific and grounded -- only use what is "
    "stated or strongly implied. Return JSON only."
)

_LLM_TEMPLATE = """\
Read this company description and return a JSON profile.

DESCRIPTION:
\"\"\"{desc}\"\"\"

Return ONLY this JSON object (no prose):
{{
  "company_name": "<short name, empty string if unclear>",
  "industry": "<concise industry, e.g. 'DTC skincare', 'B2B HR software'>",
  "business_model": "<one of: b2c | b2b | marketplace | dtc | saas>",
  "product_category": "<one of: apparel | electronics | beauty | home | food_bev | fitness | travel | finance | auto | entertainment | saas | marketing_agency | professional_services | general>",
  "value_proposition": "<one sentence summarising the customer benefit>",
  "target_customer_summary": "<one sentence on who buys from them>",
  "price_position": "<one of: value | mid | premium | luxury>",
  "brand_tone": "<one of: bold | friendly | premium | technical | neutral>"
}}"""


def _parse_via_llm(description: str) -> CompanyProfile | None:
    text = text_complete(_LLM_TEMPLATE.format(desc=description.strip()),
                          system=_LLM_SYSTEM, max_tokens=500, json_mode=True)
    parsed = extract_json(text)
    if not parsed:
        return None
    return CompanyProfile(
        raw_description=description,
        company_name=str(parsed.get("company_name", "")).strip(),
        industry=str(parsed.get("industry", "")).strip(),
        business_model=_normalise(parsed.get("business_model", "b2c"),
                                   {"b2c", "b2b", "marketplace", "dtc",
                                    "saas"}, "b2c"),
        product_category=_normalise(parsed.get("product_category", "general"),
                                     _CATEGORIES, "general"),
        value_proposition=str(parsed.get("value_proposition", "")).strip(),
        target_customer_summary=str(
            parsed.get("target_customer_summary", "")).strip(),
        price_position=_normalise(parsed.get("price_position", "mid"),
                                   {"value", "mid", "premium", "luxury"},
                                   "mid"),
        brand_tone=_normalise(parsed.get("brand_tone", "neutral"),
                               {"bold", "friendly", "premium",
                                "technical", "neutral"}, "neutral"),
        source="llm",
    )


def _normalise(val, allowed: set, default: str) -> str:
    s = str(val or "").strip().lower()
    return s if s in allowed else default


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------

_CATEGORIES = {"apparel", "electronics", "beauty", "home", "food_bev",
               "fitness", "travel", "finance", "auto", "entertainment",
               "saas", "marketing_agency", "professional_services",
               "general"}

# More-specific multi-word categories come FIRST so a "marketing agency for
# DTC fashion brands" isn't swallowed by the "apparel" keyword set.
_CATEGORY_KEYWORDS = {
    "marketing_agency": ["marketing agency", "creative agency",
                          "advertising agency", "growth agency",
                          "marketing studio", "ad agency", "marketing firm",
                          "branding agency", "digital agency"],
    "professional_services": ["consultancy", "consulting", "law firm",
                                "accounting firm", "professional services",
                                "advisory", "services firm"],
    "saas": ["saas", "software-as-a-service", "developer tool",
              "b2b software", "cloud platform", " api ", "no-code"],
    "apparel": ["clothing", "apparel", "fashion", "shoes", "outfit",
                 "streetwear", "athleisure"],
    "electronics": ["electronics", "gadget", "device", "phone", "laptop",
                     "headphones", "smartwatch"],
    "beauty": ["beauty", "skincare", "cosmetics", "makeup", "fragrance",
                "perfume", "haircare"],
    "home": ["furniture", "home", "homeware", "decor", "kitchenware",
              "candles"],
    "food_bev": ["food", "beverage", "snack", "coffee", "tea", "drink",
                  "restaurant", "meal", "brewery", "wine", "beer",
                  "smoothie"],
    "fitness": ["fitness", "gym", "workout", "training", "wellness",
                 "running", "runner", "cycling", "cyclist", "yoga",
                 "pilates", "crossfit", "marathon", "club", "sport",
                 "sports", "athletic", "outdoors", "hiking", "climbing",
                 "swimming"],
    "travel": ["travel", "booking", "hotel", "airline", "trip", "tour",
                "tourism", "vacation"],
    "finance": ["bank", "finance", "fintech", "lending", "insurance",
                 "credit", "payments", "investment", "broker", "wealth"],
    "auto": ["car", "auto", "vehicle", "ev", "automotive"],
    "entertainment": ["movie", "music", "game", "streaming", "podcast",
                       "video", "media", "concert", "festival"],
}

_B2B_HINTS = ["b2b", "enterprise", "saas", "platform", "api", "software",
              "tool for teams", "for companies", "for businesses"]
_DTC_HINTS = ["dtc", "direct to consumer", "shop online", "our website",
              "shipping"]
_PREMIUM_HINTS = ["premium", "luxury", "high-end", "designer", "artisan",
                  "handcrafted"]
_VALUE_HINTS = ["affordable", "budget", "cheap", "low-cost", "discount",
                "value"]


def _parse_heuristic(description: str) -> CompanyProfile:
    desc = description.strip()
    desc_lower = desc.lower()

    # company name: first capitalised word/phrase or "<name> is/does..."
    name = ""
    m = re.search(r"^([A-Z][\w&.\- ]{1,40}?)\s+(?:is|does|builds|sells|"
                   r"offers|helps|makes|provides|launched)", desc)
    if m:
        name = m.group(1).strip()
    elif desc.split():
        first = desc.split(".")[0].split(",")[0]
        if first and first[0].isupper() and len(first.split()) <= 6:
            name = first

    # business model
    model = "b2c"
    if any(h in desc_lower for h in _B2B_HINTS):
        model = "b2b"
    elif any(h in desc_lower for h in _DTC_HINTS):
        model = "dtc"

    # product category
    category = "general"
    for cat, words in _CATEGORY_KEYWORDS.items():
        if any(w in desc_lower for w in words):
            category = cat
            break

    # price position
    price = "mid"
    if any(h in desc_lower for h in _PREMIUM_HINTS):
        price = "premium"
    elif "luxury" in desc_lower:
        price = "luxury"
    elif any(h in desc_lower for h in _VALUE_HINTS):
        price = "value"

    # heuristic industry label — keep distinct from price_position (own field)
    # and business_model (own field) so we don't end up with "Mid fitness".
    if category == "general":
        industry = "General consumer"
    else:
        industry = category.replace("_", " ").title()
        # "Saas" reads better as "SaaS"
        if category == "saas":
            industry = "SaaS"
    if model == "b2b" and not industry.lower().startswith("b2b"):
        industry = "B2B " + industry

    return CompanyProfile(
        raw_description=description,
        company_name=name,
        industry=industry,
        business_model=model,
        product_category=category,
        value_proposition="",
        target_customer_summary="",
        price_position=price,
        brand_tone="neutral",
        source="heuristic",
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def parse_company(description: str, prefer_llm: bool = True) -> CompanyProfile:
    """Parse a free-text company description into a structured profile.

    Tries LLM first when ``prefer_llm`` is True; falls back to the heuristic
    if no LLM is available or the call fails / returns malformed JSON.
    """
    description = (description or "").strip()
    if not description:
        return CompanyProfile(raw_description="", source="empty")
    if prefer_llm:
        profile = _parse_via_llm(description)
        if profile is not None:
            return profile
    return _parse_heuristic(description)
