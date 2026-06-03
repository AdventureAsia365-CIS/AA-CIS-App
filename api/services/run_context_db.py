"""
Asyncpg helpers for acp_shared.acp_run_context.

get_run_context_validated  — load + validate; raises RunContextValidationError on bad row
write_run_context_stage    — atomic per-stage UPDATE; each stage touches only its own columns
"""
import json
from typing import Any

from api.schemas.run_context import (
    RunContext,
    RunContextValidationError,
    S0StagePayload,
    S1StagePayload,
    S2StagePayload,
    S3StagePayload,
)

_STAGE_COLUMNS = {
    "s0": ("brand_brief",),
    "s1": ("s1_keywords_used",),
    "s2": (
        "s2_keyword_research",
        "s2_visibility_report",
        "s2_keyword_clusters",
        "s2_market_preference",
        "s2_aa_tour_matches",
        "s2_confidence_score",
        "s2_keywords_s3_key",
        "s2_report_s3_key",
    ),
    "s3": ("s3_content_calendar", "s3_ads_plan", "s3_funnel_mix"),
}

_STAGE_PAYLOAD_MODELS = {
    "s0": S0StagePayload,
    "s1": S1StagePayload,
    "s2": S2StagePayload,
    "s3": S3StagePayload,
}

_JSONB_COLUMNS = {
    "brand_brief", "s1_keywords_used",
    "s2_keyword_research", "s2_visibility_report",
    "s2_keyword_clusters", "s2_market_preference", "s2_aa_tour_matches",
    "s3_content_calendar", "s3_ads_plan", "s3_funnel_mix",
}


async def get_run_context_validated(
    conn,
    run_id: str,
    require_stages: tuple[str, ...] = (),
) -> RunContext:
    """
    Load the full context row and return a validated RunContext.

    Args:
        conn: asyncpg connection or pool.acquire() result
        run_id: UUID string
        require_stages: stage names whose fields must be non-None (e.g. ("s2",))

    Raises:
        RunContextValidationError if the row is missing or a required stage field is None
    """
    row = await conn.fetchrow(
        "SELECT * FROM acp_shared.acp_run_context WHERE run_id=$1::uuid",
        run_id,
    )
    if not row:
        raise RunContextValidationError(
            run_id=run_id,
            missing_path="<row>",
            detail="no acp_run_context row exists",
        )

    ctx = RunContext(
        run_id=str(row["run_id"]),
        tenant_id=str(row["tenant_id"]),
        brand_brief=_parse_jsonb(row.get("brand_brief")),
        s1_keywords_used=_parse_jsonb(row.get("s1_keywords_used")),
        s2_keyword_research=_parse_jsonb(row.get("s2_keyword_research")),
        s2_visibility_report=_parse_jsonb(row.get("s2_visibility_report")),
        s2_keyword_clusters=_parse_jsonb(row.get("s2_keyword_clusters")),
        s2_market_preference=_parse_jsonb(row.get("s2_market_preference")),
        s2_aa_tour_matches=_parse_jsonb(row.get("s2_aa_tour_matches")),
        s2_confidence_score=_to_float(row.get("s2_confidence_score")),
        s2_keywords_s3_key=row.get("s2_keywords_s3_key"),
        s2_report_s3_key=row.get("s2_report_s3_key"),
        s3_content_calendar=_parse_jsonb(row.get("s3_content_calendar")),
        s3_ads_plan=_parse_jsonb(row.get("s3_ads_plan")),
        s3_funnel_mix=_parse_jsonb(row.get("s3_funnel_mix")),
    )

    for stage in require_stages:
        for col in _STAGE_COLUMNS.get(stage, ()):
            if getattr(ctx, col, None) is None:
                raise RunContextValidationError(
                    run_id=run_id,
                    missing_path=col,
                    detail=f"stage '{stage}' output required by downstream",
                )

    return ctx


async def write_run_context_stage(
    conn,
    run_id: str,
    stage: str,
    payload: dict[str, Any],
) -> None:
    """
    Atomic per-stage UPDATE — touches only the columns owned by `stage`.

    Validates `payload` with the stage Pydantic model before writing.
    Each stage writes to disjoint columns, so concurrent stage writes cannot clobber each other.

    Args:
        conn: asyncpg connection (not pool — must be within an acquired connection)
        run_id: UUID string
        stage: "s0" | "s1" | "s2" | "s3"
        payload: dict matching the stage Pydantic model fields
    """
    if stage not in _STAGE_PAYLOAD_MODELS:
        raise ValueError(f"Unknown stage '{stage}'. Expected one of {list(_STAGE_PAYLOAD_MODELS)}")

    model_cls = _STAGE_PAYLOAD_MODELS[stage]
    validated = model_cls(**payload)
    data = validated.model_dump()

    cols = _STAGE_COLUMNS[stage]
    set_clauses = []
    params: list[Any] = []
    param_idx = 1

    for col in cols:
        val = data.get(col)
        if col in _JSONB_COLUMNS:
            set_clauses.append(f"{col} = ${param_idx}::jsonb")
            params.append(json.dumps(val) if val is not None else None)
        else:
            set_clauses.append(f"{col} = ${param_idx}")
            params.append(val)
        param_idx += 1

    set_clauses.append("updated_at = NOW()")
    params.append(run_id)

    sql = (
        f"UPDATE acp_shared.acp_run_context "
        f"SET {', '.join(set_clauses)} "
        f"WHERE run_id = ${param_idx}::uuid"
    )
    await conn.execute(sql, *params)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_jsonb(val: Any) -> Any:
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
