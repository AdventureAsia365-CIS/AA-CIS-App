"""
Deterministic S2 confidence scorer (AA-105).

Replaces the LLM-generated confidence_score anti-pattern.
Each dimension is scored independently from observable state values.

Returns (score, dimensions) — caller logs dimensions to run_context.
"""


def compute_confidence(
    keyword_count: int,
    competitor_count: int,
    cache_hit_rate: float,
    gsc_data: bool,
) -> tuple[float, dict]:
    """Compute a 0.0–1.0 confidence score from deterministic signal dimensions.

    Args:
        keyword_count:    total keywords collected (dataforseo + expand)
        competitor_count: number of active competitor URLs for this tenant/country
        cache_hit_rate:   fraction of data sources that were cache hits (0.0=fully fresh)
        gsc_data:         True if GSC property data was collected

    Returns:
        (score, dimensions) where dimensions has per-source contribution floats.
    """
    dims: dict[str, float] = {}

    if keyword_count >= 20:
        dims["keywords"] = 0.40
    elif keyword_count >= 10:
        dims["keywords"] = 0.20
    else:
        dims["keywords"] = 0.0

    if competitor_count >= 3:
        dims["competitors"] = 0.30
    elif competitor_count >= 1:
        dims["competitors"] = 0.15
    else:
        dims["competitors"] = 0.0

    # Fresh data (low cache rate) signals higher reliability
    dims["freshness"] = 0.20 if cache_hit_rate < 0.5 else 0.0

    dims["gsc"] = 0.10 if gsc_data else 0.0

    score = round(sum(dims.values()), 2)
    return score, dims
