"""AA-362 [N8-2] — piece_metric_data()/emit_piece_metrics() CloudWatch shape.

Convention check: reuses namespace "acp" (the only real precedent in this
repo, api/routers/acp_health.py), best-effort emit that never raises.
"""
from unittest.mock import MagicMock, patch

from services.acp_produce.metrics import emit_piece_metrics, piece_metric_data
from services.acp_produce.models import GateResult, Piece


def _piece(status="passed", repair_count=0, gate_ledger=None):
    return Piece(
        piece_id="p1", body_tagged="body", status=status,
        repair_count=repair_count, gate_ledger=gate_ledger or [],
    )


# ── piece_metric_data() — pure ──────────────────────────────────────────────

def test_in_progress_piece_emits_nothing():
    piece = _piece(status="in_progress")
    assert piece_metric_data(piece) == []


def test_passed_piece_emits_passed_1_held_0():
    piece = _piece(status="passed", repair_count=1)
    data = {m["MetricName"]: m["Value"] for m in piece_metric_data(piece)}
    assert data["piece_passed"] == 1.0
    assert data["piece_held"] == 0.0
    assert data["repair_count"] == 1.0


def test_held_piece_emits_held_1_passed_0():
    piece = _piece(status="held", repair_count=3)
    data = {m["MetricName"]: m["Value"] for m in piece_metric_data(piece)}
    assert data["piece_passed"] == 0.0
    assert data["piece_held"] == 1.0
    assert data["repair_count"] == 3.0


def test_grounding_score_1_when_f1_passed():
    ledger = [GateResult(gate="F1_grounding", passed=True, violations=[])]
    piece = _piece(status="passed", gate_ledger=ledger)
    data = {m["MetricName"]: m["Value"] for m in piece_metric_data(piece)}
    assert data["grounding_score"] == 1.0


def test_grounding_score_0_when_f1_failed():
    ledger = [GateResult(gate="F1_grounding", passed=False, violations=["unknown id"])]
    piece = _piece(status="held", gate_ledger=ledger)
    data = {m["MetricName"]: m["Value"] for m in piece_metric_data(piece)}
    assert data["grounding_score"] == 0.0


def test_grounding_score_absent_when_f1_never_ran():
    ledger = [GateResult(gate="F8_framework", passed=True, violations=[])]
    piece = _piece(status="passed", gate_ledger=ledger)
    data = {m["MetricName"]: m["Value"] for m in piece_metric_data(piece)}
    assert "grounding_score" not in data


def test_all_metrics_have_valid_cloudwatch_units():
    ledger = [GateResult(gate="F1_grounding", passed=True, violations=[])]
    piece = _piece(status="passed", gate_ledger=ledger)
    for m in piece_metric_data(piece):
        assert m["Unit"] in ("Count", "None")
        assert isinstance(m["Value"], float)


# ── emit_piece_metrics() — boto3 mocked, no real AWS call ──────────────────

def test_emit_calls_put_metric_data_with_acp_namespace():
    piece = _piece(status="passed", repair_count=0)
    fake_cw = MagicMock()
    with patch("services.acp_produce.metrics.boto3.client", return_value=fake_cw) as mock_client:
        emit_piece_metrics(piece, region="us-west-1")

    mock_client.assert_called_once_with("cloudwatch", region_name="us-west-1")
    fake_cw.put_metric_data.assert_called_once()
    _, kwargs = fake_cw.put_metric_data.call_args
    assert kwargs["Namespace"] == "acp"
    names = {m["MetricName"] for m in kwargs["MetricData"]}
    assert names == {"piece_passed", "piece_held", "repair_count"}


def test_emit_skips_put_metric_data_when_piece_not_terminal():
    piece = _piece(status="in_progress")
    fake_cw = MagicMock()
    with patch("services.acp_produce.metrics.boto3.client", return_value=fake_cw):
        emit_piece_metrics(piece)
    fake_cw.put_metric_data.assert_not_called()


def test_emit_never_raises_on_cloudwatch_error():
    piece = _piece(status="passed")
    with patch("services.acp_produce.metrics.boto3.client", side_effect=RuntimeError("boom")):
        emit_piece_metrics(piece)  # must not raise
