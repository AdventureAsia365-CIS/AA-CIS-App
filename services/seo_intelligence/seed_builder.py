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
# AA-515: extended from {US, UK, AU} to also cover DE/FR/NL — confirmed via a live query
# against shared.tenant_seo_config (STEP0c, docs/claude_audit/AA-515-step0c-multimarket-
# schema.md) that a real tenant (exploreasia-co) already declares target_market.countries =
# [DE, FR, NL], none of which resolve_buyer_market() could previously return (silently fell
# back to US — a market that tenant never even listed). Codes are the standard Google Ads
# location criteria IDs (Germany/France/Netherlands), same numbering family as the 3 already
# here.
DFS_LOCATION_MAP = {
    "US": (2840, "United States"),
    "UK": (2826, "United Kingdom"),
    "AU": (2036, "Australia"),
    "DE": (2276, "Germany"),
    "FR": (2250, "France"),
    "NL": (2528, "Netherlands"),
}

# Buyer-market preference when a tenant targets several countries (lower = preferred).
# Used by resolve_buyer_market() (singular, unchanged) to pick ONE market. resolve_buyer_
# markets() (plural, AA-515) does not consult this for exclusion — it returns EVERY market in
# DFS_LOCATION_MAP a tenant declares, ranked by this only for a stable, arguable ordering.
MARKET_RANK = {"US": 1, "UK": 2, "AU": 3, "DE": 4, "FR": 5, "NL": 6}

# AA-515: reverse lookup, location_code -> 2-letter market code. resolve_buyer_markets() returns
# the literal (location_code, location_name, language_code) 3-tuple shape the build prompt asked
# for (matching resolve_buyer_market()'s own contract) — it does not carry the 2-letter code
# alongside it, so a caller that needs to persist a compact "market" column (acp_contract.
# search_demand/atom_ranking, AA-515) looks it up here rather than re-deriving it.
LOCATION_CODE_TO_MARKET = {code: market for market, (code, _name) in DFS_LOCATION_MAP.items()}

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


def build_seed(country_raw: str, activities, tour_name: str = "") -> str:
    """Complete DFS seed. Never produces a double 'tours'.

    AA-251 (ADR-2026-021, hướng 4): priority is activity+country (most specific,
    unchanged AA-197 behavior) > tour_name+country > country-only "{country} tours".
    The country-only fallback made the seed — and every DFS keyword derived from
    it — generic, which is what made DFS_INTENT_UNDERUSED false-positive across
    ~85% of the KR/LK catalogue. tour_name (raw_tours.src_name, always populated)
    is the nearest per-tour specificity available without a live per-tour DFS call.
    """
    c = normalize_country(country_raw)
    a = first_activity(activities)
    if a and c:
        return f"{a} in {c}"
    n = (tour_name or "").strip()
    if n:
        return f"{n} {c}".strip() if c else n
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


def resolve_buyer_markets(target_market: dict) -> list[tuple[int, str, str]]:
    """EVERY market a tenant sells to, not just the single highest-priority one.

    AA-515 (STEP0c, docs/claude_audit/AA-515-step0c-multimarket-schema.md): a live query
    confirmed all 3 real tenants already store multiple countries in `target_market.countries`
    (3 each) — resolve_buyer_market() (singular, kept UNCHANGED above) was always throwing 2 of
    3 away, not because the data was thin. This is a NEW function, not a signature change to
    the existing one — 3 real call sites (services/seo_intelligence/handler.py:58,
    api/routers/admin_pipeline.py:2296, admin_pipeline.py:2507) all destructure a single
    3-tuple and would break if resolve_buyer_market() started returning a list instead.

    Returns one (location_code, location_name, language_code) per country in
    `target_market.countries` that DFS_LOCATION_MAP knows, ordered by MARKET_RANK (unranked-
    but-known markets — none exist today, but sort stably if that changes — fall after every
    ranked one). Unknown-only or empty -> [US] (the same single-market fallback
    resolve_buyer_market() already uses), never an empty list — a caller fanning out per market
    should not need a separate empty-list branch for "no usable market" versus "one market,
    the default".
    """
    tm = target_market or {}
    countries = tm.get("countries") or []
    lang = tm.get("language", "en") or "en"

    known = [c for c in countries if c in DFS_LOCATION_MAP]
    if not known:
        known = [_DEFAULT_MARKET]
    # dict.fromkeys dedupes while keeping first-seen order stable before the rank-sort, in case
    # a tenant's countries array ever repeats a code.
    ordered = sorted(dict.fromkeys(known), key=lambda c: (MARKET_RANK.get(c, 999), c))
    return [(*DFS_LOCATION_MAP[c], lang) for c in ordered]
