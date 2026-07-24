"""
tests/unit/test_aa298_judge.py — F8 cross-weight judge (services/acp_produce/
judge_client.py + gates.py::gate_framework(), AA-298 Nhóm 3).

Covers the 3 things ADR-2026-014/ADR-2026-027/L3 require and the AA-298
verify checklist names explicitly:
  1. F8 calls Nova Pro (us.amazon.nova-pro-v1:0), not the writer's model.
  2. The payload sent to the judge contains NO trace of the writer's
     generation system/user prompt (context isolation, verified by reading
     the actual payload — not by trusting a docstring).
  3. Binary 1/0 scoring with mandatory evidence — no 1-10 scale, no silent
     pass on missing/malformed judge output.
"""
import json
from unittest.mock import MagicMock, patch

from services.acp_produce.gates import gate_brand_seo_audit, gate_framework
from services.acp_produce.judge_client import NOVA_PRO_MODEL_ID, invoke_judge


def _bedrock_response(text: str):
    payload = {
        "output": {"message": {"content": [{"text": text}], "role": "assistant"}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 30},
    }
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode()
    return {"body": body}


def test_invoke_judge_calls_nova_pro_model_id():
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _bedrock_response('{"ok": true}')
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client) as mock_boto:
        result = invoke_judge("system", "user")

    mock_boto.assert_called_once_with("bedrock-runtime", region_name="us-west-1")
    call_kwargs = fake_client.invoke_model.call_args.kwargs
    assert call_kwargs["modelId"] == NOVA_PRO_MODEL_ID == "us.amazon.nova-pro-v1:0"
    assert result["provider"] == "bedrock-acc2"


def test_invoke_judge_never_the_writer_model_id():
    """Direct assertion the checklist asks for: judge model != writer model."""
    from services.content_generation.s1_from_atom import PALMYRA_MODEL_ID
    assert NOVA_PRO_MODEL_ID != PALMYRA_MODEL_ID


def test_gate_framework_context_isolation_no_generation_prompt_in_judge_payload():
    """L3: judge must never see the writer's generation system/user prompt.
    Verified here by reading the EXACT payload sent to Nova and asserting the
    writer's real system prompt text is absent from it."""
    from services.content_generation.s1_from_atom import _GROUNDING_SYSTEM_PROMPT

    fake_client = MagicMock()
    good_items = {"items": [{"criterion": c, "score": "1", "evidence": "quote"}
                             for c in ["covers the topic comprehensively via subsections",
                                       "each section answers a distinct sub-question"]]}
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps(good_items))

    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        gate_framework("Some piece body about a trip to Sri Lanka.", "hub")

    sent_body = json.loads(fake_client.invoke_model.call_args.kwargs["body"])
    sent_system = sent_body["system"][0]["text"]
    sent_user = sent_body["messages"][0]["content"][0]["text"]

    # The writer's actual production system prompt must not leak into the judge call.
    assert _GROUNDING_SYSTEM_PROMPT not in sent_system
    assert _GROUNDING_SYSTEM_PROMPT not in sent_user
    assert "CLOSED WORLD RULE" not in sent_system  # a distinctive phrase unique to the writer prompt
    assert "CLOSED WORLD RULE" not in sent_user


def test_judge_client_module_never_imports_generation_or_writer_modules():
    """Structural check, not just a docstring promise: judge_client.py's own
    IMPORT STATEMENTS (not docstrings/comments, which legitimately reference
    the writer modules to explain the isolation) must not reference the
    writer's modules."""
    import ast
    import inspect

    from services.acp_produce import judge_client
    tree = ast.parse(inspect.getsource(judge_client))
    imported_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    assert not any("content_generation" in name for name in imported_names)
    assert not any("acp_produce.generation" in name for name in imported_names)


def test_gate_framework_passes_when_all_criteria_scored_1_with_evidence():
    fake_client = MagicMock()
    data = {"items": [
        {"criterion": "opens with the reader's problem", "score": "1", "evidence": "Your bags are packed..."},
        {"criterion": "agitates concretely", "score": "1", "evidence": "the layover drags on..."},
        {"criterion": "resolves with the trip as solve", "score": "1", "evidence": "This trip fixes that."},
    ]}
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps(data))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result = gate_framework("piece text", "PAS")
    assert result.passed is True
    assert result.violations == []


def test_gate_framework_fails_on_score_0():
    fake_client = MagicMock()
    data = {"items": [{"criterion": "single clear action (CTA)", "score": "0", "evidence": ""}]}
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps(data))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result = gate_framework("piece text", "AIDA")
    assert result.passed is False
    assert any("single clear action" in v for v in result.violations)


def test_gate_framework_treats_score_1_without_evidence_as_fail():
    """Mandatory evidence citation — a 1 with no quote does not count."""
    fake_client = MagicMock()
    data = {"items": [{"criterion": "ends with CTA", "score": "1", "evidence": ""}]}
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps(data))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result = gate_framework("piece text", "hook_story_cta")
    assert result.passed is False
    assert any("no evidence" in v for v in result.violations)


def test_gate_framework_treats_empty_judge_output_as_fail_not_silent_pass():
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps({"items": []}))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result = gate_framework("piece text", "hub")
    assert result.passed is False
    assert any("no rubric items" in v for v in result.violations)


def test_gate_framework_unknown_framework_falls_back_to_default_rubric():
    fake_client = MagicMock()
    data = {"items": [{"criterion": "structure matches the stated framework", "score": "1", "evidence": "quote"}]}
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps(data))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client) as mock_boto:
        result = gate_framework("piece text", "some_unknown_framework")
    assert result.passed is True
    sent_body = json.loads(mock_boto.return_value.invoke_model.call_args.kwargs["body"])
    assert "structure matches the stated framework" in sent_body["messages"][0]["content"][0]["text"]


# ── F9 brand_seo_audit ────────────────────────────────────────────────────

def test_gate_brand_seo_audit_passes_on_status_pass():
    fake_client = MagicMock()
    data = {"status": "pass", "brand_fit": 1, "human_read": 1, "seo_fit": 1,
            "trip_type_accuracy": 1, "publish_readiness": 1, "failure_codes": [], "notes": "clean"}
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps(data))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result, audit = gate_brand_seo_audit("piece text", "brand rubric text")
    assert result.passed is True
    assert audit["status"] == "pass"


def test_gate_brand_seo_audit_fails_with_failure_codes_on_flagged():
    fake_client = MagicMock()
    data = {"status": "flagged", "brand_fit": 0, "human_read": 1, "seo_fit": 1,
            "trip_type_accuracy": 1, "publish_readiness": 0,
            "failure_codes": ["SUMMARY_OFF_BRAND", "GENERIC_AI_WORDING"], "notes": "reads like AI filler"}
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps(data))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result, audit = gate_brand_seo_audit("piece text", "brand rubric text")
    assert result.passed is False
    assert "SUMMARY_OFF_BRAND" in result.violations[0]
    assert audit["failure_codes"] == ["SUMMARY_OFF_BRAND", "GENERIC_AI_WORDING"]


def test_gate_brand_seo_audit_drops_failure_codes_outside_fixed_vocabulary():
    """The judge must not be able to invent its own label — anything outside
    BRAND_SEO_FAILURE_CODES is silently dropped from the tracked set (but
    status=flagged/manual_check still fails the gate)."""
    fake_client = MagicMock()
    data = {"status": "flagged", "failure_codes": ["SUMMARY_OFF_BRAND", "MADE_UP_CODE_XYZ"]}
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps(data))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result, audit = gate_brand_seo_audit("piece text", "brand rubric text")
    assert audit["failure_codes"] == ["SUMMARY_OFF_BRAND"]
    assert result.passed is False


def test_gate_brand_seo_audit_context_isolation():
    from services.content_generation.s1_from_atom import _GROUNDING_SYSTEM_PROMPT

    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _bedrock_response(json.dumps({"status": "pass", "failure_codes": []}))
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        gate_brand_seo_audit("piece text", "brand rubric text")

    sent_body = json.loads(fake_client.invoke_model.call_args.kwargs["body"])
    assert _GROUNDING_SYSTEM_PROMPT not in json.dumps(sent_body)


def test_gate_brand_seo_audit_judge_unavailable_returns_none_audit_not_fabricated():
    fake_client = MagicMock()
    fake_client.invoke_model.side_effect = RuntimeError("Bedrock throttled")
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result, audit = gate_brand_seo_audit("piece text", "brand rubric text")
    assert result.passed is False
    assert audit is None  # no fabricated audit dict when the judge call itself failed
