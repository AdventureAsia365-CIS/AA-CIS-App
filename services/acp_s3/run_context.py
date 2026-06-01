"""
psycopg2-based run_context helpers for the S3 Lambda.

The Lambda cannot import asyncpg, so this module provides synchronous equivalents
of the api/services/run_context_db.py helpers using psycopg2.

Shares the same Pydantic schema from api/schemas/run_context.py via sys.path insertion
done by the Lambda build step (or by the tests via PYTHONPATH).
"""
import json
import sys
import os
from typing import Any

# Allow importing api.schemas from the Lambda package (added to PYTHONPATH at build time)
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from api.schemas.run_context import (  # noqa: E402
    RunContext,
    RunContextValidationError,
    S3StagePayload,
)

_JSONB_COLS = {
    "s3_content_calendar", "s3_ads_plan", "s3_funnel_mix",
}


def get_run_context_sync(conn, run_id: str, require_stages: tuple[str, ...] = ()) -> RunContext:
    """
    Load and validate run_context with psycopg2 RealDictCursor.

    Raises RunContextValidationError if the row is absent or required fields are None.
    """
    import psycopg2.extras

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM acp_shared.acp_run_context WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()

    if not row:
        raise RunContextValidationError(
            run_id=run_id,
            missing_path="<row>",
            detail="no acp_run_context row exists",
        )

    ctx = RunContext(
        run_id=str(row["run_id"]),
        tenant_id=str(row["tenant_id"]),
        brand_brief=_parse(row.get("brand_brief")),
        s1_keywords_used=_parse(row.get("s1_keywords_used")),
        s2_keyword_research=_parse(row.get("s2_keyword_research")),
        s2_visibility_report=_parse(row.get("s2_visibility_report")),
        s2_keyword_clusters=_parse(row.get("s2_keyword_clusters")),
        s2_market_preference=_parse(row.get("s2_market_preference")),
        s2_aa_tour_matches=_parse(row.get("s2_aa_tour_matches")),
        s2_confidence_score=_to_float(row.get("s2_confidence_score")),
        s3_content_calendar=_parse(row.get("s3_content_calendar")),
        s3_ads_plan=_parse(row.get("s3_ads_plan")),
        s3_funnel_mix=_parse(row.get("s3_funnel_mix")),
    )

    _S3_COLS = ("s3_content_calendar", "s3_ads_plan", "s3_funnel_mix")
    _S2_COLS = (
        "s2_keyword_research", "s2_visibility_report",
        "s2_keyword_clusters", "s2_market_preference", "s2_aa_tour_matches",
        "s2_confidence_score",
    )
    _COL_MAP = {"s2": _S2_COLS, "s3": _S3_COLS}

    for stage in require_stages:
        for col in _COL_MAP.get(stage, ()):
            if getattr(ctx, col, None) is None:
                raise RunContextValidationError(
                    run_id=run_id,
                    missing_path=col,
                    detail=f"stage '{stage}' output required by S3",
                )

    return ctx


def write_s3_stage_sync(conn, run_id: str, payload: dict[str, Any]) -> None:
    """
    Atomic UPDATE for S3 stage columns only.

    Validates payload with S3StagePayload before writing.
    Only touches s3_content_calendar, s3_ads_plan, s3_funnel_mix, updated_at.
    """
    validated = S3StagePayload(**payload)
    data = validated.model_dump()

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE acp_shared.acp_run_context SET
                s3_content_calendar = %s::jsonb,
                s3_ads_plan         = %s::jsonb,
                s3_funnel_mix       = %s::jsonb,
                updated_at          = NOW()
            WHERE run_id = %s
            """,
            (
                json.dumps(data["s3_content_calendar"]),
                json.dumps(data["s3_ads_plan"]),
                json.dumps(data["s3_funnel_mix"]),
                run_id,
            ),
        )


def _parse(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return val


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
