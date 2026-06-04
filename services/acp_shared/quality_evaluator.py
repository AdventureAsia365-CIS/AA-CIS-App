"""Isolated quality evaluator for S4.2 Social Media Content Engine (AA-120).

Evaluates post quality on 5 dimensions via Bedrock Haiku.
Isolated: accepts only post_text + platform — no brand brief or strategy context
to prevent self-grading bias.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

import structlog

logger = structlog.get_logger(__name__)

QUALITY_DIMENSIONS = ['hook_strength', 'specificity', 'cta_clarity', 'brand_voice', 'audience_fit']
QUALITY_PASS_THRESHOLD = 3.0

_EVALUATOR_SYSTEM = """You are a social media content quality evaluator.
Rate the post on 5 dimensions, scale 1-5. Return ONLY valid JSON, no explanation."""

_EVALUATOR_USER = """Rate this {platform} post on 5 dimensions, scale 1-5:
- hook_strength: Does the first line stop scrolling?
- specificity: Are details concrete and specific (not vague)?
- cta_clarity: Is the call to action obvious and actionable?
- brand_voice: Does it sound premium, not salesy or generic?
- audience_fit: Is it appropriate for affluent adventure travelers?

Post:
{post_text}

Return ONLY valid JSON:
{{"hook_strength": N, "specificity": N, "cta_clarity": N, "brand_voice": N, "audience_fit": N}}"""


@dataclass
class QualityScore:
    hook_strength: float
    specificity: float
    cta_clarity: float
    brand_voice: float
    audience_fit: float
    average: float
    passed: bool
    raw_response: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> 'QualityScore':
        scores = {k: float(d.get(k, 0)) for k in QUALITY_DIMENSIONS}
        avg = sum(scores.values()) / len(scores)
        return cls(
            **scores,
            average=round(avg, 2),
            passed=avg >= QUALITY_PASS_THRESHOLD,
        )


def evaluate_quality(
    post_text: str,
    platform: str,
    llm_client: Callable,
) -> QualityScore:
    user_prompt = _EVALUATOR_USER.format(
        platform=platform,
        post_text=post_text[:2000],
    )
    try:
        raw = llm_client(_EVALUATOR_SYSTEM, user_prompt)
        json_match = re.search(r'\{[^}]+\}', raw)
        if not json_match:
            raise ValueError(f'No JSON in evaluator response: {raw[:200]}')
        scores = json.loads(json_match.group())
        result = QualityScore.from_dict(scores)
        result.raw_response = raw
        logger.info(
            'quality_eval_done',
            platform=platform,
            average=result.average,
            passed=result.passed,
        )
        return result
    except Exception as e:
        logger.error('quality_eval_failed', error=str(e))
        return QualityScore(
            hook_strength=0, specificity=0, cta_clarity=0,
            brand_voice=0, audience_fit=0, average=0.0,
            passed=False, raw_response=str(e),
        )
