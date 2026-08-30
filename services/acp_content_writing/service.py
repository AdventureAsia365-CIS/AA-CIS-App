"""
services.acp_content_writing.service — T9 + T10-inline orchestration.

AA-466: /write is now 202 Accepted + poll (real API Gateway 504s on long LLM+T10 runs,
AA-453/465 — up to 2 attempts x (1 write/rewrite LLM call + 1 T10 gate check) could run ~89s).
`start_write()` does everything that was always fast/no-LLM (fetch+validate the request,
resolve goal/channel/brand/atom/trip context, insert a `content_piece` placeholder row with
status='processing') and is awaited synchronously by the router — same 404/409/422 error
contract as before. `run_write_background()` is the part that was always slow (the write/rewrite
+ T10-check loop) — launched via `asyncio.create_task()` by the router (strong-ref pattern, see
that file) and updates the SAME placeholder row in place when done. The write/check loop body
itself is UNCHANGED from the pre-AA-466 single-function version — only the HTTP/persistence
layer around it moved.

Max 2 total write attempts, confirmed cap (Phase 1 §2c's real N7 convergence data: judge-class
checks converge on repair only 2.5%-14.6% of the time — a low cap is better supported by that
data than N7's own 3-8 round range, which was calibrated for a background job with no tenant
waiting on it).

Every blocking LLM call (write, rewrite, and quality_gates.py's 2 judge gates) runs inside
`asyncio.to_thread()` from the very first version of this module — not patched in after an
incident, per the build task's explicit instruction and Phase 1's own documented lesson from
N7 (AA-416 only fixed this symptom after 2 real production ALB-timeout incidents).
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional
from uuid import UUID

import structlog

from services.acp_angle_gate import service as angle_gate_service
from services.acp_angle_gate.brand_audience import fetch_brand_audience
from services.acp_angle_gate.channel_style import get_channel_style
from services.acp_angle_gate.goals import get_goal
from services.acp_content_writing.generate import rewrite_with_feedback, write_content
from services.acp_content_writing.quality_gates import (deep_strip_citation_tags, run_quality_gates,
                                                          strip_citation_tags)
from services.acp_planning.tenant_pool import fetch_tenant_trips
from services.acp_produce.brand import fetch_brand_rubric_text

logger = structlog.get_logger()

MAX_ATTEMPTS = 2  # Phase 1 §2c/§3 — confirmed cap, not N7's 3-8 range


class ContentWritingError(Exception):
    """Base class for this package's own domain errors."""


class RequestNotReadyError(ContentWritingError):
    """T9 requires angle_gate_request.status == 'approved' AND channel already set (T8 workflow
    steps 1-8 complete — AA-469 Việc 4 added step 8, picking a channel, AFTER the angle choice
    that used to be the last gate here)."""


class MissingCTAError(ContentWritingError):
    """Neither angle_gate_request.cta (usually NULL today, see migration 114's header) nor a
    tenant-supplied cta_override was available. STEP0's Open Question #2 resolved: T9 asks
    rather than fabricates a generic per-channel CTA (SKILL_v2.md's own step 4 says "ask for
    the specific CTA" — a human decision, not an inferred one)."""


_ATOM_TEXT_QUERY = """
    SELECT text FROM acp_contract.tour_atoms
    WHERE atom_id = $1 AND owner_scope = $2 AND NOT deleted AND NOT is_empty_marker
"""


async def _fetch_atom_text(tenant_id: UUID, atom_id: str, pool) -> str:
    """Tenant-scoped, kept local per the same precedent AA-449 already set for
    services/acp_angle_gate/service.py::_fetch_atom_for_tenant() ("kept local here rather than
    added to tenant_pool.py since it's T8-specific") — this one is T9-specific and only needs
    the text field, not the full atom dict T8's version returns."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_ATOM_TEXT_QUERY, atom_id, str(tenant_id))
    if row is None:
        raise ContentWritingError(f"atom_id={atom_id!r} not found for this tenant")
    return row["text"]


def _held_reason_from(first_failure: dict) -> str:
    return f"{first_failure['gate']}: {'; '.join(first_failure['violations'][:3])}"


async def start_write(
    tenant_id: UUID, request_id: UUID, pool, cta_override: Optional[str] = None,
) -> dict:
    """Fast pre-flight (no LLM call) — everything write_and_check() used to do before its
    write/check loop. Raises RequestNotReadyError / MissingCTAError /
    angle_gate_service.RequestNotFoundError — the router maps each to an HTTP status, UNCHANGED
    from the pre-AA-466 synchronous contract for these specific conditions. On success, inserts
    the `content_piece` placeholder row (status='processing') and returns it — the router
    returns this as the 202 body, then launches run_write_background() with the piece_id."""
    # AA-497 (AA-494 Decision 3) — verified this guard needs NO change. The reopen -> re-choose
    # cycle (services/acp_angle_gate/service.py::reopen_request()/choose_angle()) always lands
    # back on 'approved' before a second write can happen — choose_angle()'s final UPDATE sets
    # 'approved' unconditionally regardless of whether it was called from 'pending_choice' or
    # 'reusable' — so this function never actually sees status='reusable' in practice, confirming
    # the design intent stated in AA-497's own task description.
    req = await angle_gate_service.fetch_request(tenant_id, request_id, pool)
    if req["status"] != "approved":
        raise RequestNotReadyError(
            f"request_id={request_id} is status={req['status']!r}, expected 'approved' — "
            "T8's angle-choice step (workflow step 7) must be complete before T9 can write."
        )
    if not req["channel"]:
        # AA-469 Việc 4 (flow-order fix) — channel is now a separate step (8) AFTER angle
        # choice, set via angle_gate_service.set_channel(), not a create_request() param
        # anymore. Defensive in practice: the real UI always calls .../channel before ever
        # reaching the write step, so this should be unreachable via the shipped flow — kept as
        # a real error (not a silent fallback) if that invariant is ever violated, same
        # reasoning as the "chosen is None" defensive check just below.
        raise RequestNotReadyError(
            f"request_id={request_id} has no channel set — T8's channel-choice step "
            "(workflow step 8) must be complete before T9 can write."
        )
    chosen = next((a for a in req["angles"] if a["chosen"]), None)
    if chosen is None:
        # Defensive — choose_angle() (T8) always sets exactly one chosen=true before flipping
        # status to 'approved'; this is unreachable via the real API, kept as a real error
        # rather than a silent fallback if that invariant is ever violated.
        raise ContentWritingError(f"request_id={request_id} is approved but has no chosen angle")

    cta = req["cta"] or cta_override
    if not cta or not cta.strip():
        raise MissingCTAError(
            f"request_id={request_id} has no CTA (angle_gate_request.cta is NULL — see "
            "migration 114) and no cta_override was supplied in the write request."
        )

    atom_text = await _fetch_atom_text(tenant_id, req["atom_id"], pool)
    goal = get_goal(req["goal"])
    if goal is None:
        raise ContentWritingError(f"request_id={request_id} has an unknown goal={req['goal']!r}")
    channel_style = get_channel_style(req["channel"])
    if channel_style is None:
        raise ContentWritingError(f"request_id={request_id} has an unknown channel={req['channel']!r}")
    brand_audience = await fetch_brand_audience(tenant_id, pool)

    destination = trip_name = None
    if req["trip_id"]:
        trips = await fetch_tenant_trips(tenant_id, pool)
        trip = next((t for t in trips if str(t.id) == req["trip_id"]), None)
        if trip:
            trip_name = trip.name
            destination = trip.destination

    async with pool.acquire() as conn:
        brand_rubric_text = await fetch_brand_rubric_text(conn, str(tenant_id))

    # AA-497 — angle_gate_option_id (migration 124's Decision 2 column, unpopulated until now):
    # denormalized record of WHICH of the 3 options this specific piece was written from, so a
    # piece's history stays accurate even after a later reopen()+re-choice changes `chosen` on
    # the request. `chosen["option_id"]` is present because fetch_request() (AA-497) now selects
    # it — a request written before this change has no rows to backfill (0 approved requests
    # existed live as of this migration, confirmed via STEP0-refresh), so there's no gap to close.
    option_id = chosen.get("option_id")
    # AA-469 Việc 4 (flow-order fix) — content_piece.channel (migration 124's Decision 2 column,
    # unpopulated until now per that migration's own header) finally has a real value to write:
    # channel is set on the request (angle_gate_service.set_channel(), step 8) before a write can
    # even start (see the guard above), so req["channel"] is always real here.
    piece = await _insert_placeholder_piece(
        pool, tenant_id=tenant_id, request_id=request_id, angle_gate_option_id=option_id,
        channel=req["channel"],
    )

    context = {
        "atom_text": atom_text, "goal": goal, "channel_style": channel_style,
        "brand_audience": brand_audience, "chosen": chosen, "cta": cta,
        "destination": destination, "trip_name": trip_name,
        "brand_rubric_text": brand_rubric_text, "channel": req["channel"],
        "atom_id": req["atom_id"],
    }
    return {"piece": piece, "context": context}


async def _insert_placeholder_piece(
    pool, *, tenant_id: UUID, request_id: UUID, angle_gate_option_id=None, channel=None,
) -> dict:
    # AA-497 (migration 125) — attempt_number=1 is still correct as the INITIAL value for every
    # new write session (T9's own internal retry loop, run_write_background(), overwrites it via
    # _finalize_piece() with the final 1-or-2 it actually took) — this is no longer required to
    # be unique per angle_gate_request_id (migration 125 dropped that constraint), since a
    # reopened request can now have more than one content_piece row over time.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO acp_shared.content_piece
                (tenant_id, angle_gate_request_id, angle_gate_option_id, channel, attempt_number,
                 content_text, status)
            VALUES ($1, $2, $3, $4, 1, '', 'processing')
            RETURNING piece_id, tenant_id, angle_gate_request_id, attempt_number, content_text,
                      status, held_reason, gate_ledger, repair_log, created_at
            """,
            tenant_id, request_id, angle_gate_option_id, channel,
        )
    return _row_to_dict(row)


async def run_write_background(request_id: UUID, piece_id: UUID, context: dict, pool) -> None:
    """The write/rewrite + T10-check loop — UNCHANGED body from the pre-AA-466 single-function
    write_and_check(), just reading its inputs from `context` (built by start_write()) instead
    of local variables, and calling `_finalize_piece()` (an UPDATE by piece_id) instead of
    `_persist_piece()` (an INSERT). Launched via `asyncio.create_task()` + strong-ref (see
    api/routers/v1_content_writing.py) — same GC-safety pattern api/routers/v1_tours.py's
    `trigger_rewrite()` already established (AA-425), not the bare `asyncio.create_task()`
    v1_s4_blog.py uses. Any uncaught exception here means the background task itself failed
    (Bedrock throttle, network error, anything) BEFORE producing real content — written back as
    status='failed', distinct from status='held' (a real, complete, gate-blocked outcome with
    real content_text) — see migration 118's header for why these must not be conflated."""
    atom_text, goal, channel_style = context["atom_text"], context["goal"], context["channel_style"]
    brand_audience, chosen, cta = context["brand_audience"], context["chosen"], context["cta"]
    destination, trip_name = context["destination"], context["trip_name"]
    brand_rubric_text, channel, atom_id = context["brand_rubric_text"], context["channel"], context["atom_id"]

    attempt = 1  # bound before the try block so the except handler always has a real value
    try:
        total_cost = 0.0
        content_text: str = ""
        gate_ledger: list[dict] = []
        repair_log: list[dict] = []
        status = "held"
        held_reason = "unreachable"  # overwritten every branch below; kept non-None for mypy/clarity

        for attempt in range(1, MAX_ATTEMPTS + 1):
            if attempt == 1:
                content_text, cost = await asyncio.to_thread(
                    write_content, content_seed=atom_text, goal=goal, channel_style=channel_style,
                    brand_audience=brand_audience, angle=chosen, cta=cta,
                    destination=destination, trip_name=trip_name, atom_id=atom_id,
                )
            else:
                content_text, cost = await asyncio.to_thread(
                    rewrite_with_feedback, content_seed=atom_text, goal=goal, channel_style=channel_style,
                    brand_audience=brand_audience, angle=chosen, cta=cta,
                    revision_feedback=repair_log[-1]["violations"],
                    destination=destination, trip_name=trip_name, atom_id=atom_id,
                )
            total_cost += cost

            outcome = await asyncio.to_thread(
                run_quality_gates, content_text=content_text, atom_text=atom_text, cta=cta,
                goal_key=goal["key"], brand_rubric_text=brand_rubric_text, channel=channel,
            )
            gate_ledger = outcome["gate_ledger"]

            if outcome["passed"]:
                status, held_reason = "approved", None
                break

            first_failure = outcome["first_failure"]
            repair_log.append({
                "attempt": attempt, "gate_targeted": first_failure["gate"],
                "violations": first_failure["violations"], "repairable": first_failure["repairable"],
            })
            logger.info(
                "t9_attempt_failed_quality_check", request_id=str(request_id), attempt=attempt,
                gate=first_failure["gate"], repairable=first_failure["repairable"],
            )

            if not first_failure["repairable"] or attempt >= MAX_ATTEMPTS:
                status, held_reason = "held", _held_reason_from(first_failure)
                break

        # AA-452 — mandatory, tenant-facing-leak-prevention step: strip every [R:atom_id]/[F:id]
        # citation tag (channel='blog' only ever produces one, prompts.py's _BLOG_FORMAT_INSTRUCTIONS)
        # from content_text AND from every gate_ledger/repair_log violation string (a gate's own
        # violation message can itself quote a tagged excerpt — see quality_gates.gate_grounding()'s
        # own comment) BEFORE this piece is persisted or returned, regardless of status ('approved'
        # or 'held' both go through this — a held piece is still fully visible to the tenant per
        # _hold()'s own "hold VISIBLE, never silent" precedent, so a held piece leaking a raw tag
        # would be exactly as real a leak as an approved one). Runs unconditionally for every
        # channel — a no-op for the 7 that never produce a tag, real for blog.
        content_text = strip_citation_tags(content_text)
        gate_ledger = deep_strip_citation_tags(gate_ledger)
        repair_log = deep_strip_citation_tags(repair_log)
        if held_reason:
            held_reason = strip_citation_tags(held_reason)

        await _finalize_piece(
            pool, piece_id=piece_id, attempt_number=attempt,
            content_text=content_text, status=status, held_reason=held_reason,
            gate_ledger=gate_ledger, repair_log=repair_log,
        )
        logger.info(
            "t9_write_and_check_done", request_id=str(request_id), status=status,
            attempts=attempt, cost_usd=total_cost,
        )
    except Exception as exc:
        logger.error(
            "t9_write_background_failed", request_id=str(request_id), piece_id=str(piece_id),
            attempt=attempt, error_type=type(exc).__name__, error=str(exc),
        )
        try:
            await _finalize_piece(
                pool, piece_id=piece_id, attempt_number=attempt, content_text="",
                status="failed", held_reason=f"{type(exc).__name__}: {exc}",
                gate_ledger=[], repair_log=[],
            )
        except Exception:
            logger.error(
                "t9_write_background_failed_status_write_also_failed",
                request_id=str(request_id), piece_id=str(piece_id),
            )


async def _finalize_piece(
    pool, *, piece_id: UUID, attempt_number: int, content_text: str,
    status: str, held_reason: Optional[str], gate_ledger: list[dict], repair_log: list[dict],
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE acp_shared.content_piece
            SET attempt_number = $2, content_text = $3, status = $4, held_reason = $5,
                gate_ledger = $6::jsonb, repair_log = $7::jsonb
            WHERE piece_id = $1
            RETURNING piece_id, tenant_id, angle_gate_request_id, attempt_number, content_text,
                      status, held_reason, gate_ledger, repair_log, created_at
            """,
            piece_id, attempt_number, content_text, status, held_reason,
            json.dumps(gate_ledger), json.dumps(repair_log),
        )
    return _row_to_dict(row)


def _row_to_dict(row) -> dict:
    gate_ledger = row["gate_ledger"]
    repair_log = row["repair_log"]
    return {
        "piece_id": str(row["piece_id"]),
        "tenant_id": str(row["tenant_id"]),
        "angle_gate_request_id": str(row["angle_gate_request_id"]),
        "attempt_number": row["attempt_number"],
        "content_text": row["content_text"],
        "status": row["status"],
        "held_reason": row["held_reason"],
        "gate_ledger": json.loads(gate_ledger) if isinstance(gate_ledger, str) else gate_ledger,
        "repair_log": json.loads(repair_log) if isinstance(repair_log, str) else repair_log,
        "created_at": row["created_at"].isoformat(),
    }


async def fetch_piece(tenant_id: UUID, piece_id: UUID, pool) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT piece_id, tenant_id, angle_gate_request_id, attempt_number, content_text,
                   status, held_reason, gate_ledger, repair_log, created_at
            FROM acp_shared.content_piece
            WHERE piece_id = $1 AND tenant_id = $2
            """,
            piece_id, tenant_id,
        )
    if row is None:
        raise ContentWritingError(f"piece_id={piece_id} not found for this tenant")
    return _row_to_dict(row)


# ── AA-501: tenant-facing pre-T11 review (deliberately narrower than fetch_piece() above) ──────

_READY_STATE_MAP = {
    "approved": "ready",
    "processing": "in_progress",
    "held": "not_ready",
    "failed": "not_ready",
}

_LATEST_PIECE_FOR_REQUEST_QUERY = """
    SELECT piece_id, status, content_text, channel, angle_gate_option_id, created_at
    FROM acp_shared.content_piece
    WHERE angle_gate_request_id = $1 AND tenant_id = $2
    ORDER BY created_at DESC
    LIMIT 1
"""
# Deliberately does NOT select gate_ledger/repair_log/held_reason — STEP0 §4's own
# recommendation was to strip these at the SQL layer, not just the API response layer, so a
# future field added to fetch_review()'s dict can never accidentally leak them by copying
# fetch_piece()'s SELECT list.

_ATOM_CONTEXT_QUERY = """
    SELECT text, activity_type, emotional_hook, season_note
    FROM acp_contract.tour_atoms
    WHERE atom_id = $1 AND owner_scope = $2 AND NOT deleted AND NOT is_empty_marker
"""


async def _fetch_atom_context(tenant_id: UUID, atom_id: str, pool) -> Optional[dict]:
    """Tenant-scoped atom context for the review screen (AA-501) — text/activity_type/
    emotional_hook/season_note only, the fields the build task asked for (distinctiveness/
    persona_fit/media are AA-internal signals, out of scope here). Same owner_scope=tenant_id
    convention as this module's own _fetch_atom_text() / acp_angle_gate.service.
    _fetch_atom_for_tenant() — not a new security pattern."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_ATOM_CONTEXT_QUERY, atom_id, str(tenant_id))
    return dict(row) if row else None


async def fetch_review(tenant_id: UUID, request_id: UUID, pool) -> dict:
    """AA-501 — the tenant-facing pre-T11 review: full write context (atom/tour/goal/angle/
    DFS-PAA/channel) plus the latest content_piece for this request, WITHOUT any of T10's
    technical detail. This is deliberately STRICTER than GET .../pieces/{piece_id}
    (fetch_piece() above, which the T8/T9 wizard's own end-of-flow card uses and which DOES
    return held_reason) — Nghiệp confirmed this divergence explicitly for the new screen, it is
    not an inconsistency to reconcile.

    `content_piece` is no longer 1-row-per-request since migration 125 (AA-497 reopen/re-write) —
    picks the LATEST piece by created_at, never assumes attempt_number orders across a request's
    lifetime (STEP0 §1's own warning).

    Raises angle_gate_service.RequestNotFoundError (request doesn't exist / isn't this tenant's,
    propagates from fetch_request() below) or ContentWritingError (request exists but T9 has
    never written anything under it yet) — the router maps both to 404."""
    req = await angle_gate_service.fetch_request(tenant_id, request_id, pool)

    async with pool.acquire() as conn:
        piece_row = await conn.fetchrow(_LATEST_PIECE_FOR_REQUEST_QUERY, request_id, tenant_id)
    if piece_row is None:
        raise ContentWritingError(
            f"request_id={request_id} has no written content yet — T9's write step hasn't run "
            "for this request."
        )

    # AA-469 Việc 4 — same COALESCE(cp.channel, agr.channel) every other real read site uses
    # (v1_publish.py, admin_a4.py's content-log): a piece's own channel is immutable once
    # written; the parent request's channel can move on to a different value before its NEXT
    # write session.
    channel = piece_row["channel"] or req["channel"]

    # AA-497 — option_id-first join, chosen=true fallback only for pre-AA-497 rows with no
    # angle_gate_option_id, same lesson v1_publish.py already applies (chosen is mutable after a
    # reopen(), a piece's own angle_gate_option_id is not).
    option_id = piece_row["angle_gate_option_id"]
    angle = None
    if option_id:
        angle = next((a for a in req["angles"] if a["option_id"] == option_id), None)
    if angle is None:
        angle = next((a for a in req["angles"] if a["chosen"]), None)

    atom_context = await _fetch_atom_context(tenant_id, req["atom_id"], pool)

    tour_context = None
    if req["trip_id"]:
        trips = await fetch_tenant_trips(tenant_id, pool)
        trip = next((t for t in trips if str(t.id) == req["trip_id"]), None)
        if trip:
            tour_context = {"name": trip.name, "destination": trip.destination}

    goal_obj = get_goal(req["goal"]) if req["goal"] else None

    ready_state = _READY_STATE_MAP.get(piece_row["status"], "not_ready")
    # Content is only meaningful to show for approved/held — migration 115/118's own "held keeps
    # real writer output visible for review, failed/processing never produced any" distinction.
    # 'failed'/'processing' rows have content_text = '' by construction, never a partial draft.
    content_text = piece_row["content_text"] if piece_row["status"] in ("approved", "held") else None

    return {
        "request_id": req["request_id"],
        "channel": channel,
        "ready_state": ready_state,
        "content_text": content_text,
        "goal": (
            {"key": req["goal"], "label": goal_obj["name"] if goal_obj else req["goal"]}
            if req["goal"] else None
        ),
        "angle": (
            {
                "name": angle["name"], "why_it_works": angle["why_it_works"],
                "formula_fit": angle["formula_fit"], "best_final_style": angle["best_final_style"],
            } if angle else None
        ),
        "atom": atom_context,
        "tour": tour_context,
        "dfs_paa_snapshot": req["dfs_paa_snapshot"],
        "cta": req["cta"],
        "created_at": piece_row["created_at"].isoformat(),
    }


# AA-501 — the browse-all-pieces list `/portal/t10-review` shows (build task: "Danh sách bài viết
# theo channel, mỗi bài mở ra xem đủ ngữ cảnh"). One row per angle_gate_request (its LATEST
# content_piece, same AA-497 "no longer 1:1" rule as fetch_review() above), full context embedded
# directly — no separate per-row detail fetch, matching how admin_a4.py's content-log and this
# app's other list endpoints already return everything up front rather than a paginated
# expand-fetch. Deliberately does NOT select gate_ledger/repair_log/held_reason, same as
# fetch_review().
_TENANT_REVIEWS_QUERY = """
    SELECT * FROM (
        SELECT DISTINCT ON (cp.angle_gate_request_id)
            cp.piece_id, cp.angle_gate_request_id, cp.status, cp.content_text,
            cp.created_at,
            COALESCE(cp.channel, agr.channel) AS channel, agr.goal, agr.cta,
            agr.trip_id, agr.dfs_paa_snapshot,
            COALESCE(ago.name, ago_chosen.name) AS angle_name,
            COALESCE(ago.why_it_works, ago_chosen.why_it_works) AS angle_why_it_works,
            COALESCE(ago.formula_fit, ago_chosen.formula_fit) AS angle_formula_fit,
            COALESCE(ago.best_final_style, ago_chosen.best_final_style) AS angle_best_final_style,
            ta.text AS atom_text, ta.activity_type AS atom_activity_type,
            ta.emotional_hook AS atom_emotional_hook, ta.season_note AS atom_season_note
        FROM acp_shared.content_piece cp
        JOIN acp_shared.angle_gate_request agr ON agr.request_id = cp.angle_gate_request_id
        LEFT JOIN acp_shared.angle_gate_option ago ON ago.option_id = cp.angle_gate_option_id
        LEFT JOIN acp_shared.angle_gate_option ago_chosen
            ON ago_chosen.request_id = agr.request_id AND ago_chosen.chosen = true
            AND cp.angle_gate_option_id IS NULL
        LEFT JOIN acp_contract.tour_atoms ta
            ON ta.atom_id = agr.atom_id AND ta.owner_scope = $1::text
        WHERE cp.tenant_id = $1
        ORDER BY cp.angle_gate_request_id, cp.created_at DESC
    ) latest
    ORDER BY latest.created_at DESC
"""


async def fetch_review_list(tenant_id: UUID, pool) -> list[dict]:
    """AA-501 — GET /v1/content-writing/reviews. One call, one query (plus one
    fetch_tenant_trips() call, only when at least one row has a trip_id — never per-row) rather
    than N+1 calls into fetch_review() per request; the SQL is intentionally independent of
    fetch_review()'s own query (same precedent as admin_a4.py's content-log and v1_publish.py's
    /pending each keeping their own SQL rather than sharing an abstraction)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_TENANT_REVIEWS_QUERY, tenant_id)

    trips_by_id: dict[str, object] = {}
    if any(r["trip_id"] for r in rows):
        trips = await fetch_tenant_trips(tenant_id, pool)
        trips_by_id = {str(t.id): t for t in trips}

    items = []
    for r in rows:
        goal_obj = get_goal(r["goal"]) if r["goal"] else None
        ready_state = _READY_STATE_MAP.get(r["status"], "not_ready")
        content_text = r["content_text"] if r["status"] in ("approved", "held") else None

        tour_context = None
        trip_id = str(r["trip_id"]) if r["trip_id"] else None
        if trip_id and trip_id in trips_by_id:
            trip = trips_by_id[trip_id]
            tour_context = {"name": trip.name, "destination": trip.destination}

        snapshot = r["dfs_paa_snapshot"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)

        items.append({
            "request_id": str(r["angle_gate_request_id"]),
            "piece_id": str(r["piece_id"]),
            "channel": r["channel"],
            "ready_state": ready_state,
            "content_text": content_text,
            "goal": (
                {"key": r["goal"], "label": goal_obj["name"] if goal_obj else r["goal"]}
                if r["goal"] else None
            ),
            "angle": (
                {
                    "name": r["angle_name"], "why_it_works": r["angle_why_it_works"],
                    "formula_fit": r["angle_formula_fit"], "best_final_style": r["angle_best_final_style"],
                } if r["angle_name"] else None
            ),
            "atom": (
                {
                    "text": r["atom_text"], "activity_type": r["atom_activity_type"],
                    "emotional_hook": r["atom_emotional_hook"], "season_note": r["atom_season_note"],
                } if r["atom_text"] else None
            ),
            "tour": tour_context,
            "dfs_paa_snapshot": snapshot,
            "cta": r["cta"],
            "created_at": r["created_at"].isoformat(),
        })
    return items


__all__ = [
    "ContentWritingError", "RequestNotReadyError", "MissingCTAError", "MAX_ATTEMPTS",
    "start_write", "run_write_background", "fetch_piece", "fetch_review", "fetch_review_list",
]
