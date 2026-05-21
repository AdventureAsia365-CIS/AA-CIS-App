"""Pydantic models for S4 blog validation pipeline (AA-80)."""
from typing import Optional
from pydantic import BaseModel


class CheckResult(BaseModel):
    check_name: str
    passed: bool
    score: float
    issues: list[str]
    repair_hint: str = ""


class ValidationResult(BaseModel):
    blog_draft_id: Optional[str] = None
    overall_passed: bool
    overall_score: float
    checks: list[CheckResult]
    failing_sections: list[str]
    repair_targets: list[dict]
