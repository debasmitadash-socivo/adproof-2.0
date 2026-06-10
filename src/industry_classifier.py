"""Map a company's product_category / industry hints onto Rival IQ's
14-industry taxonomy.

The simulator's company_profile carries fields like ``product_category``
(apparel, fitness, beauty, finance, ...), ``industry`` (free-text), and
``what_they_sell`` (LLM-extracted). Rival IQ buckets companies into 14
fixed industries:

  alcohol, fashion, financial_services, food_beverage, health_beauty,
  higher_ed, home_decor, influencers, media, nonprofits, retail,
  sports_teams, tech_software, travel

We map AdProof's vocabulary to those buckets so the industry-keyed
benchmark lookup actually returns something useful. Falls back to
``None`` honestly when no match - caller decides whether to degrade
or hide the card.
"""
from __future__ import annotations

__all__ = ["map_to_rival_iq_industry"]


# Each entry is a Rival IQ slug -> tuple of signals.
# Signals are substrings checked case-insensitively against the company
# profile blob.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("alcohol",            ("alcohol", "beer", "wine", "spirit", "brewery",
                             "distillery", "bar ", "pub ", "cocktail",
                             "champagne", "whisky", "whiskey", "vodka", "gin ")),
    ("fashion",            ("fashion", "apparel", "clothing", "streetwear",
                             "menswear", "womenswear", "luxury wear",
                             "designer", "dress", "shoe", "footwear",
                             "accessory")),
    ("financial_services", ("finance", "bank", "fintech", "loan", "mortgage",
                             "credit", "invest", "wealth", "crypto", "trading",
                             "insurance", "tax")),
    ("food_beverage",      ("food", "restaurant", "cafe", "coffee", "tea",
                             "drink", "beverage", "snack", "meal", "recipe",
                             "dietary", "vegan", "vegetarian", "kitchen brand")),
    ("health_beauty",      ("beauty", "skincare", "cosmetic", "makeup",
                             "fragrance", "haircare", "wellness", "fitness",
                             "gym", "workout", "yoga", "supplement",
                             "personal care", "spa", "salon", "health",
                             "mental health")),
    ("higher_ed",          ("university", "college", "higher ed", "school",
                             "course provider", "academy", "education",
                             "online learning", "edtech", "tutoring",
                             "bootcamp")),
    ("home_decor",         ("home decor", "furniture", "interior", "homeware",
                             "kitchenware", "bedding", "lighting", "diy",
                             "garden", "appliance")),
    ("influencers",        ("influencer", "creator agency", "talent",
                             "content house", "creator economy")),
    ("media",              ("media", "newspaper", "magazine", "publisher",
                             "broadcast", "podcast", "news", "journalism",
                             "blogger", "publication")),
    ("nonprofits",         ("nonprofit", "non-profit", "ngo", "charity",
                             "foundation", "social enterprise",
                             "cause-driven")),
    ("retail",             ("retail", "ecommerce", "e-commerce", "marketplace",
                             "dtc", "direct to consumer", "shop", "store",
                             "online store", "shopify")),
    ("sports_teams",       ("sports team", "football club", "basketball",
                             "soccer", "rugby", "tennis", "athletics",
                             "olympic", "league", "stadium")),
    ("tech_software",      ("saas", "software", "tech", "developer", "api",
                             "platform", "ai ", " ai", "agency", "consult",
                             "b2b", "enterprise", "automation", "analytics",
                             "marketing tool", "cloud", "data", "cybersecurity",
                             "agency tool")),
    ("travel",             ("travel", "hotel", "airline", "tourism",
                             "vacation", "destination", "hospitality",
                             "booking platform", "airbnb-style", "tour")),
)


def map_to_rival_iq_industry(
    *,
    product_category: str | None = None,
    industry: str | None = None,
    business_model: str | None = None,
    what_they_sell: str | None = None,
    value_proposition: str | None = None,
    company_name: str | None = None,
) -> str | None:
    """Return the Rival IQ industry slug that best fits the company, or
    None when no match.

    Highest signal-hit count wins; ties broken by the order in _RULES so
    the earlier-listed (more specific) industries beat the catch-all
    'tech_software' / 'retail' buckets on equal scores.
    """
    blob = " ".join(filter(None, [
        product_category, industry, business_model,
        what_they_sell, value_proposition, company_name,
    ])).lower()
    if not blob.strip():
        return None
    scores: dict[str, int] = {}
    for slug, signals in _RULES:
        hits = sum(1 for s in signals if s in blob)
        if hits:
            scores[slug] = hits
    if not scores:
        return None
    order = {slug: idx for idx, (slug, _) in enumerate(_RULES)}
    return max(scores.items(), key=lambda kv: (kv[1], -order[kv[0]]))[0]
