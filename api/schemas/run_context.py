"""
Pydantic schema for acp_shared.acp_run_context.

One model per stage — each maps to the column(s) that stage owns.
RunContext is the aggregate (full row); stage models are the write units.
"""
from typing import Any, Optional
from pydantic import BaseModel, field_validator


class RunContextValidationError(Exception):
    """Raised when a required stage field is absent or None."""

    def __init__(self, run_id: str, missing_path: str, detail: str = ""):  # noqa: B042
        self.run_id = run_id
        self.missing_path = missing_path
        self.detail = detail
        message = (
            f"run_context validation failed for run_id={run_id}: "
            f"missing or null field '{missing_path}'"
            + (f" — {detail}" if detail else "")
        )
        super().__init__(message, run_id, missing_path, detail)


# ── Per-stage write payloads ──────────────────────────────────────────────────

class S0StagePayload(BaseModel):
    brand_brief: dict[str, Any]

    @field_validator("brand_brief")
    @classmethod
    def not_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("brand_brief must not be empty")
        return v


class S1StagePayload(BaseModel):
    s1_keywords_used: list[str]


class S2StagePayload(BaseModel):
    s2_keyword_research: dict[str, Any]
    s2_visibility_report: dict[str, Any]
    s2_keyword_clusters: Optional[list[Any]] = None
    s2_market_preference: Optional[dict[str, Any]] = None
    s2_aa_tour_matches: Optional[list[Any]] = None
    s2_confidence_score: float
    s2_keywords_s3_key: Optional[str] = None
    s2_report_s3_key: Optional[str] = None

    @field_validator("s2_confidence_score")
    @classmethod
    def valid_score(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"s2_confidence_score must be 0.0–1.0, got {v}")
        return v


class S3StagePayload(BaseModel):
    s3_content_calendar: dict[str, Any]
    s3_ads_plan: dict[str, Any]
    s3_funnel_mix: dict[str, Any]


# ── Full context row (read) ───────────────────────────────────────────────────

class RunContext(BaseModel):
    run_id: str
    tenant_id: str
    brand_brief: Optional[dict[str, Any]] = None
    s1_keywords_used: Optional[list[Any]] = None
    s2_keyword_research: Optional[dict[str, Any]] = None
    s2_visibility_report: Optional[dict[str, Any]] = None
    s2_keyword_clusters: Optional[list[Any]] = None
    s2_market_preference: Optional[dict[str, Any]] = None
    s2_aa_tour_matches: Optional[list[Any]] = None
    s2_confidence_score: Optional[float] = None
    s2_keywords_s3_key: Optional[str] = None
    s2_report_s3_key: Optional[str] = None
    s3_content_calendar: Optional[dict[str, Any]] = None
    s3_ads_plan: Optional[dict[str, Any]] = None
    s3_funnel_mix: Optional[dict[str, Any]] = None

    def require(self, *paths: str) -> None:
        """Assert each dot-path is present and non-None. Raises RunContextValidationError."""
        for path in paths:
            val = getattr(self, path, None)
            if val is None:
                raise RunContextValidationError(
                    run_id=self.run_id,
                    missing_path=path,
                    detail="required by downstream stage",
                )
