"""
tests/unit/test_aa364_pipeline.py — services/acp_produce/pipeline.py
(AA-364: first orchestrator running a Piece through output_rules -> F1/F8/F9,
persisting to acp_deliver.pieces, emitting gate-pass metrics).

DB mock follows the exact convention used for apply_output_rules_to_piece()
in test_aa363_rule_adapter.py (_Row/_make_rule/_make_db). Judge (F8/F9) mock
follows test_aa298_judge.py's `_bedrock_response()` convention.

Scope: these tests exercise the orchestrator with a hand-constructed Piece
that already has body_tagged set — exactly like every other N7 test in this
repo (test_aa298_gates.py, test_aa361/362/363_*.py). C3/E1-E5 do not exist
yet (AA-364 STEP 0) — these tests do not stand in for them.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_produce.models import Brief, KeywordRecord, Piece
from services.acp_produce.pipeline import run_piece_through_produce_gates

TENANT = "00000000-0000-0000-0000-000000000001"
RUN_ID = "11111111-1111-1111-1111-111111111111"
TOUR_ID = "22222222-2222-2222-2222-222222222222"


class _Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_rule(rule_id, rule_type, pattern, error_message=None):
    return _Row({
        "rule_id": rule_id, "rule_type": rule_type, "pattern": pattern,
        "action_value": None, "error_message": error_message or f"Rule {rule_id} violated",
    })


def _make_db(rules=None, url_alive=True):
    """`fetchval` defaults to `url_alive=True` (AA-372 F6's pre-fetch) — the
    one live-confirmed fact about `acp_deliver.tenant_tour_pages` in dev
    (0 rows, 06/08/2026) is that F6 must fail closed on a missing row, which
    a dedicated test below exercises by overriding this to `None`."""
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=rules or [])
    db.execute = AsyncMock()
    db.fetchrow = AsyncMock()
    db.fetchval = AsyncMock(return_value=url_alive)
    return db


def _piece(body_tagged, piece_id="p1", channel="blog"):
    return Piece(piece_id=piece_id, body_tagged=body_tagged, channel=channel, status="in_progress")


def _passing_brief():
    """AA-372 F4/F6 context — deliberately trivial so it's satisfied by the
    trivial passing-test body below (keyword present, no required H2s, a
    generous word_range, CTA text literally in the body)."""
    return Brief(
        brief_id="brief-1", slot_id="slot-1", keyword="rickshaw",
        demand=KeywordRecord(keyword="rickshaw", location="US"),
        required_h2s=[], word_range=(1, 100),
        cta_target="https://example.com/trip", internal_links=[],
        framework="hub",
    )


def _bedrock_response(data: dict):
    payload = {"output": {"message": {"content": [{"text": json.dumps(data)}], "role": "assistant"}},
               "usage": {"inputTokens": 10, "outputTokens": 5}}
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode()
    return {"body": body}


def _passing_framework_response():
    return _bedrock_response({"items": [
        {"criterion": "structure matches the stated framework", "score": "1", "evidence": "quote"},
    ]})


def _passing_brand_seo_response():
    return _bedrock_response({
        "status": "pass", "brand_fit": 1, "human_read": 1, "seo_fit": 1,
        "trip_type_accuracy": 1, "publish_readiness": 1, "failure_codes": [], "notes": "clean",
    })


def _boto3_router(fake_bedrock, fake_cw):
    """metrics.py and judge_client.py both `import boto3` -- the same shared
    module object (Python caches modules in sys.modules), so patching
    `services.acp_produce.metrics.boto3.client` and
    `services.acp_produce.judge_client.boto3.client` in the same `with`
    silently patch the SAME attribute twice -- whichever context manager
    enters last wins, silently discarding the other's side_effect list
    (found by reproducing the resulting "not MagicMock" TypeError directly,
    not guessed). One patch, routed by service name, is the correct fix."""
    def _router(service_name, **kwargs):
        return fake_bedrock if service_name == "bedrock-runtime" else fake_cw
    return _router


COMMON_KWARGS = dict(
    run_id=RUN_ID, tenant_id=TENANT, channel="blog", slot_id="slot-1",
    valid_ids={"atom_1"}, text_by_id={"atom_1": "Ride a rickshaw through Chandni Chowk."},
    framework="hub", brand_rubric_text="Discreet Executive Adventure brand voice.",
    stage=None, brief=_passing_brief(), tour_id=TOUR_ID,
)


# ── scenario (a): passes every gate → status=passed, persisted, metrics fire, usage_log does NOT ──

@pytest.mark.asyncio
async def test_piece_passing_all_gates_persists_passed_and_emits_metrics_but_not_usage_log():
    # Two paragraphs (F3's one-sentence-paragraph check), CTA text literally
    # present (F6's blog sub-check), keyword "rickshaw" present (F4), no
    # banned-pattern lexicon hits (F2), no "## FAQ" section (F7 no-ops).
    piece = _piece(
        "The rickshaw ride opens the trip [R:atom_1] and it is wonderful indeed.\n\n"
        "Book it at https://example.com/trip."
    )
    db = _make_db(rules=[])
    fake_cw = MagicMock()
    fake_bedrock = MagicMock()
    fake_bedrock.invoke_model.side_effect = [
        _passing_framework_response(), _passing_brand_seo_response(),
    ]

    with patch("services.acp_produce.judge_client.boto3.client",
               side_effect=_boto3_router(fake_bedrock, fake_cw)):
        result = await run_piece_through_produce_gates(piece, db=db, **COMMON_KWARGS)

    assert result.status == "passed"
    assert result.held_reason is None

    # persisted via INSERT ... ON CONFLICT
    db.execute.assert_called_once()
    sql, *params = db.execute.call_args.args
    assert "INSERT INTO acp_deliver.pieces" in sql
    assert params[0] == "p1"          # piece_id
    assert params[1] == RUN_ID        # run_id
    assert params[2] == TENANT        # tenant_id
    assert params[6] == "passed"      # status

    # gate_ledger persisted includes output_rules + the full F1-F9 stack (AA-372), in order
    gate_ledger = json.loads(params[7])
    assert [g["gate"] for g in gate_ledger] == [
        "output_rules", "F1_grounding", "F2_banned_patterns", "F3_structural_variance",
        "F4_brief_compliance", "F6_route_to_sellable", "F7_faq_dedup",
        "F8_framework", "F9_brand_seo_audit",
    ]
    assert all(g["passed"] for g in gate_ledger)

    # gate-pass metrics fired
    fake_cw.put_metric_data.assert_called_once()


def test_pipeline_module_never_references_write_usage_log():
    """Structural proof of the STEP 5 boundary (mirrors AA-298's own
    import-graph verification style for judge_client.py): pipeline.py must
    not import or CALL write_usage_log anywhere in its real code — checked
    via AST (ast.Name nodes only), not a plain substring grep, so mentioning
    it in the module's own docstring/comments (as prose explaining the
    boundary) doesn't trip this test."""
    import ast
    import inspect

    import services.acp_produce.pipeline as pipeline_module
    tree = ast.parse(inspect.getsource(pipeline_module))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "write_usage_log" not in names
    assert "write_usage_log" not in imported


# ── scenario (b): fails a gate → status=held, held_reason set, persisted ──

@pytest.mark.asyncio
async def test_piece_failing_output_rules_holds_and_short_circuits_f8_f9():
    rules = [_make_rule("r1", "block", "hidden gem", error_message="Generic cliché")]
    piece = _piece("This trip takes you to a hidden gem in the mountains [R:atom_1].")
    db = _make_db(rules=rules)
    fake_cw = MagicMock()
    fake_bedrock = MagicMock()

    with patch("services.acp_produce.judge_client.boto3.client",
               side_effect=_boto3_router(fake_bedrock, fake_cw)):
        result = await run_piece_through_produce_gates(piece, db=db, **COMMON_KWARGS)

    assert result.status == "held"
    assert result.held_reason is not None
    assert "output_rules" in result.held_reason
    # F8/F9 short-circuited — no Bedrock judge call ever made (AA-363's own
    # cost-avoidance rationale, not re-invented here)
    fake_bedrock.invoke_model.assert_not_called()

    sql, *params = db.execute.call_args.args
    assert params[6] == "held"
    assert params[10] is not None  # held_reason


@pytest.mark.asyncio
async def test_piece_failing_f1_grounding_holds_with_grounding_reason():
    piece = _piece("A made-up elephant trek happens here [R:atom_fake999].")
    db = _make_db(rules=[])
    fake_cw = MagicMock()
    fake_bedrock = MagicMock()

    with patch("services.acp_produce.judge_client.boto3.client",
               side_effect=_boto3_router(fake_bedrock, fake_cw)):
        result = await run_piece_through_produce_gates(piece, db=db, **COMMON_KWARGS)

    assert result.status == "held"
    assert "F1_grounding" in result.held_reason
    assert result.repair_count == 0  # no repair attempted — max_repairs=0


# ── brand_seo_audit persisted in its own column (D4) ──

@pytest.mark.asyncio
async def test_brand_seo_audit_persisted_in_its_own_column_when_f9_flags():
    piece = _piece("The rickshaw ride opens the trip [R:atom_1].")
    db = _make_db(rules=[])
    flagged_response = _bedrock_response({
        "status": "flagged", "brand_fit": 0, "human_read": 1, "seo_fit": 1,
        "trip_type_accuracy": 1, "publish_readiness": 0,
        "failure_codes": ["GENERIC_AI_WORDING"], "notes": "sounds generic",
    })

    fake_bedrock = MagicMock()
    fake_bedrock.invoke_model.side_effect = [_passing_framework_response(), flagged_response]

    with patch("services.acp_produce.judge_client.boto3.client",
               side_effect=_boto3_router(fake_bedrock, MagicMock())):
        result = await run_piece_through_produce_gates(piece, db=db, **COMMON_KWARGS)

    assert result.status == "held"
    sql, *params = db.execute.call_args.args
    audit = json.loads(params[8])
    assert audit["status"] == "flagged"
    assert audit["failure_codes"] == ["GENERIC_AI_WORDING"]


# ── AA-372: F2/F3/F4/F6/F7 wiring + F8/F9 channel routing ──

@pytest.mark.asyncio
async def test_f6_fails_closed_when_tenant_tour_pages_has_no_row():
    """Live-confirmed 06/08/2026: acp_deliver.tenant_tour_pages has 0 rows in
    dev, and nothing in the codebase writes to it. F6 must hold on a missing
    row (url_alive=None from fetchval), not silently pass or manual_check."""
    piece = _piece(
        "The rickshaw ride opens the trip [R:atom_1] and it is wonderful indeed.\n\n"
        "Book it at https://example.com/trip."
    )
    db = _make_db(rules=[], url_alive=None)
    fake_bedrock = MagicMock()
    fake_bedrock.invoke_model.side_effect = [
        _passing_framework_response(), _passing_brand_seo_response(),
    ]

    with patch("services.acp_produce.judge_client.boto3.client",
               side_effect=_boto3_router(fake_bedrock, MagicMock())):
        result = await run_piece_through_produce_gates(piece, db=db, **COMMON_KWARGS)

    assert result.status == "held"
    assert "F6_route_to_sellable" in result.held_reason
    f6 = next(g for g in result.gate_ledger if g.gate == "F6_route_to_sellable")
    assert f6.passed is False
    assert any("not confirmed alive" in v for v in f6.violations)


@pytest.mark.asyncio
async def test_f6_passes_when_url_alive_true_and_cta_in_body():
    piece = _piece(
        "The rickshaw ride opens the trip [R:atom_1] and it is wonderful indeed.\n\n"
        "Book it at https://example.com/trip."
    )
    db = _make_db(rules=[], url_alive=True)
    fake_bedrock = MagicMock()
    fake_bedrock.invoke_model.side_effect = [
        _passing_framework_response(), _passing_brand_seo_response(),
    ]

    with patch("services.acp_produce.judge_client.boto3.client",
               side_effect=_boto3_router(fake_bedrock, MagicMock())):
        result = await run_piece_through_produce_gates(piece, db=db, **COMMON_KWARGS)

    f6 = next(g for g in result.gate_ledger if g.gate == "F6_route_to_sellable")
    assert f6.passed is True
    assert result.status == "passed"


FACEBOOK_KWARGS = {**COMMON_KWARGS, "channel": "facebook"}
TIKTOK_KWARGS = {**COMMON_KWARGS, "channel": "tiktok"}


@pytest.mark.asyncio
async def test_facebook_piece_routes_f8_to_hook_story_cta_not_blog_hub():
    """AA-372 §2: an adapted-channel Piece has no Brief of its own, so the
    blog Brief's framework ("hub", from COMMON_KWARGS) must NOT be what F8
    judges a facebook piece against — pipeline.py must resolve
    hook_story_cta via FRAMEWORK_TABLE instead."""
    piece = _piece(
        "Ride the tuk-tuk through old town at sunrise [R:atom_1].\nHASHTAGS: #travel #asia",
        piece_id="p1#facebook", channel="facebook",
    )
    db = _make_db(rules=[])
    fake_bedrock = MagicMock()
    fake_bedrock.invoke_model.side_effect = [
        _passing_framework_response(), _passing_brand_seo_response(),
    ]

    with patch("services.acp_produce.judge_client.boto3.client",
               side_effect=_boto3_router(fake_bedrock, MagicMock())):
        await run_piece_through_produce_gates(piece, db=db, **FACEBOOK_KWARGS)

    f8_call_body = json.loads(fake_bedrock.invoke_model.call_args_list[0].kwargs["body"])
    f8_prompt = f8_call_body["messages"][0]["content"][0]["text"]
    assert "first line is the hook" in f8_prompt              # hook_story_cta criterion
    assert "covers the topic comprehensively" not in f8_prompt  # blog "hub" criterion


@pytest.mark.asyncio
async def test_tiktok_piece_routes_f9_to_social_rubric_not_blog():
    """AA-372 §3: F9 for a tiktok Piece must use the 2-field social contract
    (hook_strength/cta_clear), never the 5-field blog contract (seo_fit/
    trip_type_accuracy/etc — meaningless for a TikTok script)."""
    piece = _piece(
        "HOOK: Would you eat this?\nSCRIPT: Street food tour begins here [R:atom_1].\n"
        "VISUAL: close-up shots",
        piece_id="p1#tiktok", channel="tiktok",
    )
    db = _make_db(rules=[])
    social_response = _bedrock_response({
        "status": "pass", "hook_strength": 1, "cta_clear": 1,
        "failure_codes": [], "notes": "clean",
    })
    fake_bedrock = MagicMock()
    fake_bedrock.invoke_model.side_effect = [_passing_framework_response(), social_response]

    with patch("services.acp_produce.judge_client.boto3.client",
               side_effect=_boto3_router(fake_bedrock, MagicMock())):
        result = await run_piece_through_produce_gates(piece, db=db, **TIKTOK_KWARGS)

    f9_call_body = json.loads(fake_bedrock.invoke_model.call_args_list[1].kwargs["body"])
    f9_prompt = f9_call_body["messages"][0]["content"][0]["text"]
    assert "hook_strength" in f9_prompt
    assert "seo_fit" not in f9_prompt  # blog-only field must never leak into the social rubric

    audit = next(g for g in result.gate_ledger if g.gate == "F9_brand_seo_audit_social")
    assert audit.passed is True
