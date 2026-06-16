"""AA-197 [AA-193·F2]: DataForSEO seed + buyer-market resolution (pure, no I/O).

Builds a complete search seed from dirty raw_tours fields and resolves the DataForSEO
location/language from a tenant's target_market. Kept side-effect free so it is unit-testable
without DB or HTTP. The DFS client consumes the finished seed verbatim (no more appending
"tours" — that caused the `{country} tours tours` double-tours bug).
"""

import re

# Known dirty country values observed in silver_aa_internal.raw_tours. Extend as needed.
COUNTRY_NORMALIZE = {
    "SRI-LANDKA": "Sri Lanka",
    "OKINAWA":    "Okinawa, Japan",
}

# DataForSEO location codes (google_ads / serp). Buyer markets we support today.
DFS_LOCATION_MAP = {
    "US": (2840, "United States"),
    "UK": (2826, "United Kingdom"),
    "AU": (2036, "Australia"),
}

# Buyer-market preference when a tenant targets several countries (lower = preferred).
MARKET_RANK = {"US": 1, "UK": 2, "AU": 3}

# Sensible default when target_market has no usable country.
_DEFAULT_MARKET = "US"

# activities blob is delimited by comma, pipe (U+2502) or newline.
_ACTIVITY_SPLIT = re.compile(r"[,│\n]+")


def normalize_country(raw: str) -> str:
    """Map dirty country text to a clean display country. Empty -> ''."""
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    mapped = COUNTRY_NORMALIZE.get(s.upper())
    if mapped:
        return mapped
    # Title-case word-by-word ("south korea" -> "South Korea")
    return " ".join(w.capitalize() for w in s.split())


def first_activity(activities) -> str:
    """First activity token from the jsonb value (single-elem array wrapping a delimited string)."""
    if not activities or not isinstance(activities, list):
        return ""
    first = activities[0]
    if first is None:
        return ""
    for token in _ACTIVITY_SPLIT.split(str(first)):
        token = token.strip()
        if token:
            return token
    return ""


def build_seed(country_raw: str, activities) -> str:
    """Complete DFS seed. Never produces a double 'tours'."""
    c = normalize_country(country_raw)
    a = first_activity(activities)
    if a and c:
        return f"{a} in {c}"
    if c:
        return f"{c} tours"
    return ""


def resolve_buyer_market(target_market: dict) -> tuple[int, str, str]:
    """(location_code, location_name, language_code) from tenant target_market.

    Picks the highest-priority (lowest MARKET_RANK) country present in target_market.countries.
    Empty/unknown -> US default. language passthrough (defaults 'en').
    """
    tm = target_market or {}
    countries = tm.get("countries") or []
    lang = tm.get("language", "en") or "en"

    present = [c for c in countries if c in MARKET_RANK]
    chosen = min(present, key=lambda c: MARKET_RANK[c]) if present else _DEFAULT_MARKET
    location_code, location_name = DFS_LOCATION_MAP.get(chosen, DFS_LOCATION_MAP[_DEFAULT_MARKET])
    return location_code, location_name, lang
