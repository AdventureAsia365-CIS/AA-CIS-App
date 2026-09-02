"""
services.acp_content_writing.generate — the T9 write call (SKILL_v2.md workflow step 9) and the
attempt-2 rewrite call (feedback-driven, not a fresh write).

LLM layer: shared.llm_client.client.LLMClient (model_tier="sonnet") — the same "exclusive layer"
T7/T8 already use, confirmed by STEP0 (docs/claude_audit/AA-450-00-...md §6) using the exact
3-way reasoning services/acp_angle_gate/generate.py's own docstring already worked through for
T8's angle-generation call: T9 writes ONE short single-channel piece (same job shape as the old,
not-reused acp_s4_social/writer.py), not the multi-H2 long-form draft
services/acp_produce/generation.py's Bedrock-satellite-acc1-Sonnet-only path is locked to
(AA-334), and not a cross-vendor quality judge (judge_client.py's Nova Pro, reserved for
quality_gates.py's F8/F9-equivalent gates — a writer must never share a model with the judge
scoring it, ADR-2026-014/027).

Deliberately SYNCHRONOUS functions, not `async def` — same "wrap at the async/sync boundary, not
inside every helper" decision AA-416 already made and documented
(docs/implementation-notes/AA-416-fix-event-loop-blocking.md) for the exact same class of
blocking Bedrock call. service.py (this package's async orchestrator) wraps every call here in
`await asyncio.to_thread(...)` — built in from the start per the build task's own explicit
instruction, not patched in later after a production incident the way N7's own fix was.
"""
from __future__ import annotations

from services.acp_angle_gate.brand_audience import BrandAudience
from services.acp_angle_gate.channel_style import ChannelStyle
from services.acp_angle_gate.goals import Goal
from services.acp_content_writing.prompts import SYSTEM_PROMPT, build_user_prompt
from shared.llm_client.client import LLMClient
from shared.llm_client.models import LLMRequest

# Same ceiling class as T8's angle-gen call (max_tokens=2048 for 3 short structured angles) and
# the project-wide "max_tokens=4096, not 2000" JSON-truncation rule — sized generously for the
# longest real channel example seen in this codebase (the old, not-reused acp_s4_social's
# newsletter ceiling, ~600 words ≈ 800 output tokens) with real margin, not tuned per channel
# (STEP0 confirmed no per-channel number has a real source to tune against yet).
_MAX_TOKENS = 2048


def _strip_fences(raw: str) -> str:
    """Same defensive strip content_generation/graph.py::generate_node() and
    services/acp_angle_gate/generate.py both already use — the system prompt asks for plain text,
    not JSON, but a model wrapping its answer in a markdown fence anyway is a real, seen failure
    mode worth guarding against cheaply."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            # drop a leading language tag line if present (e.g. "```text\n...")
            first_line, _, rest = raw.partition("\n")
            if rest and len(first_line.split()) <= 1:
                raw = rest
        raw = raw.strip()
    return raw


def write_content(
    *, content_seed: str, goal: Goal, channel_style: ChannelStyle,
    brand_audience: BrandAudience, angle: dict, cta: str,
    destination: str | None = None, trip_name: str | None = None, atom_id: str | None = None,
    route_segments: list[tuple[str, str]] | None = None,
) -> tuple[str, float]:
    """Attempt 1 — SKILL_v2.md workflow step 9, fresh write. Returns (content_text, cost_usd).

    `atom_id` (AA-452, defaults to `None` so every pre-AA-452 caller/test is unaffected): passed
    straight through to `build_user_prompt()` — only consumed there, and only for `channel=='blog'`
    (see that function's own docstring).

    `route_segments` (AA-513, defaults to `None` so every pre-AA-513 caller/test is unaffected):
    a Route/Blog pick's own (atom_id, text) pairs in day order — passed straight through, see
    build_user_prompt()'s own docstring."""
    user_prompt = build_user_prompt(
        content_seed=content_seed, goal=goal, channel_style=channel_style,
        brand_audience=brand_audience, angle=angle, cta=cta,
        destination=destination, trip_name=trip_name, atom_id=atom_id,
        route_segments=route_segments,
    )
    client = LLMClient()
    request = LLMRequest(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt,
                          model_tier="sonnet", max_tokens=_MAX_TOKENS)
    resp = client.generate(request)
    return _strip_fences(resp.content), resp.cost_usd


def rewrite_with_feedback(
    *, content_seed: str, goal: Goal, channel_style: ChannelStyle,
    brand_audience: BrandAudience, angle: dict, cta: str, revision_feedback: list[str],
    destination: str | None = None, trip_name: str | None = None, atom_id: str | None = None,
    route_segments: list[tuple[str, str]] | None = None,
) -> tuple[str, float]:
    """Attempt 2 (the only retry — Phase 1's confirmed cap of 2 total attempts) — the SAME
    write call, with `revision_feedback` (the specific gate/violation strings T10 failed on,
    Phase 1 §2a's confirmed "specific, not generic" feedback shape) appended to the prompt. A
    fresh full write from the same brief, not a diff/patch — same "return the full corrected
    text, never a partial section" contract N7's own repair.py documents, kept here because it's
    the right contract, not because it's ported code (this module imports nothing from
    services.acp_produce.repair)."""
    user_prompt = build_user_prompt(
        content_seed=content_seed, goal=goal, channel_style=channel_style,
        brand_audience=brand_audience, angle=angle, cta=cta,
        destination=destination, trip_name=trip_name, revision_feedback=revision_feedback,
        atom_id=atom_id, route_segments=route_segments,
    )
    client = LLMClient()
    request = LLMRequest(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt,
                          model_tier="sonnet", max_tokens=_MAX_TOKENS)
    resp = client.generate(request)
    return _strip_fences(resp.content), resp.cost_usd


__all__ = ["write_content", "rewrite_with_feedback"]
