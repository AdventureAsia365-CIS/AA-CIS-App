"""AA-289 Part B — services/eval/regression.py: regression detection + golden-tours parsing.

No live DB / no live Bedrock / no live S3: _detect_regression is pure, _download_golden_tours
is exercised against a real in-memory openpyxl workbook (same shape as the real fixture) so a
column-name drift in the fixture would actually be caught, not just mocked away.
"""
import io
from unittest.mock import MagicMock, patch

import openpyxl

from services.eval.regression import (
    S1_OLD_REGRESSION_THRESHOLD, _detect_regression, _download_golden_tours,
)


# ── _detect_regression: s1_old (avg_quality_score) ──────────────────────────

def test_detect_regression_s1_old_no_baseline_is_never_a_regression():
    current = {"avg_quality_score": 3.0}  # even a terrible score, first-ever run
    assert _detect_regression("s1_old", current, None) is False


def test_detect_regression_s1_old_small_drop_not_flagged():
    current = {"avg_quality_score": 8.0}
    baseline = {"avg_quality_score": 8.5}  # 0.5 drop, under threshold
    assert _detect_regression("s1_old", current, baseline) is False


def test_detect_regression_s1_old_big_drop_flagged():
    current = {"avg_quality_score": 6.5}
    baseline = {"avg_quality_score": 8.5}  # 2.0 drop, over the 1.0 threshold
    assert _detect_regression("s1_old", current, baseline) is True


def test_detect_regression_s1_old_drop_exactly_at_threshold_not_flagged():
    """Strictly greater than the threshold, not >= — a drop of exactly 1.0 is noise-adjacent,
    not yet a confirmed regression."""
    current = {"avg_quality_score": 7.5}
    baseline = {"avg_quality_score": 8.5}
    assert (baseline["avg_quality_score"] - current["avg_quality_score"]) == S1_OLD_REGRESSION_THRESHOLD
    assert _detect_regression("s1_old", current, baseline) is False


def test_detect_regression_s1_old_score_improved_not_flagged():
    current = {"avg_quality_score": 9.5}
    baseline = {"avg_quality_score": 8.0}
    assert _detect_regression("s1_old", current, baseline) is False


def test_detect_regression_s1_old_missing_scores_not_flagged():
    """No scored tours in the current run (e.g. all failed to parse) -> nothing to compare,
    must not crash on None - None."""
    current = {"avg_quality_score": None}
    baseline = {"avg_quality_score": 8.0}
    assert _detect_regression("s1_old", current, baseline) is False


# ── _detect_regression: s1_from_atom (gate pass rate) ────────────────────────

def test_detect_regression_s1_from_atom_no_baseline_is_never_a_regression():
    current = {"gate_pass_count": 2}
    assert _detect_regression("s1_from_atom", current, None) is False


def test_detect_regression_s1_from_atom_same_pass_count_not_flagged():
    current = {"gate_pass_count": 4}
    baseline = {"gate_pass_count": 4}
    assert _detect_regression("s1_from_atom", current, baseline) is False


def test_detect_regression_s1_from_atom_fewer_passes_flagged():
    """A tour that used to clear the grounding gate now failing it is a hard correctness
    regression, not noise — any drop counts, unlike s1_old's numeric threshold."""
    current = {"gate_pass_count": 3}
    baseline = {"gate_pass_count": 4}
    assert _detect_regression("s1_from_atom", current, baseline) is True


def test_detect_regression_s1_from_atom_more_passes_not_flagged():
    current = {"gate_pass_count": 4}
    baseline = {"gate_pass_count": 3}
    assert _detect_regression("s1_from_atom", current, baseline) is False


# ── _download_golden_tours: real openpyxl parsing, no mocked DataFrame ──────

def _build_fixture_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Golden Tours"
    header = [
        "tour_id", "country", "name", "subtitle", "trip_type", "duration", "group_size",
        "price_usd", "summary", "highlights", "itinerary_summary", "inclusions",
        "best_time_to_go", "expected_quality_score_min", "expected_quality_score_max",
        "expected_failure_codes", "annotation_notes", "chromadb_tags",
    ]
    ws.append(header)
    ws.append([
        "GT-TH-001", "Thailand", "Northern Highlands Traverse", "11 Days | Chiang Mai",
        "trekking", "11 days / 10 nights", "2-8 private", "$3,400",
        "A sustained traverse through northern Thailand's highlands.",
        "Guided ridge walk above Doi Mae Salong\nEvening with a Lisu weaver in Ban Rak Thai",
        "D1: Arrive Chiang Mai. D2-3: Doi Suthep foothills.",
        "Private guiding | Boutique lodges", "November-February", 7.5, 9,
        "None expected", "Strong golden example.", "trekking | thailand",
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_download_golden_tours_parses_real_workbook_shape():
    fixture_bytes = _build_fixture_bytes()
    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = {"Body": io.BytesIO(fixture_bytes)}

    with patch("services.eval.regression.boto3.client", return_value=fake_s3):
        tours = _download_golden_tours()

    assert len(tours) == 1
    t = tours[0]
    assert t["name"] == "Northern Highlands Traverse"
    assert t["country"] == "Thailand"
    assert t["itineraries"] == "D1: Arrive Chiang Mai. D2-3: Doi Suthep foothills."
    # highlights column is \n-joined in the fixture -> must become a real list, not a raw string
    assert t["highlights"] == [
        "Guided ridge walk above Doi Mae Salong",
        "Evening with a Lisu weaver in Ban Rak Thai",
    ]
    assert t["description"] == ""  # no equivalent column in the golden fixture


def test_download_golden_tours_skips_blank_trailing_rows():
    """openpyxl's iter_rows can yield fully-empty rows past the real data (common after manual
    Excel edits/saves) — a row with no tour_id must be skipped, not turned into a fake blank
    tour that would silently drag down avg_quality_score."""
    fixture_bytes = _build_fixture_bytes()
    wb = openpyxl.load_workbook(io.BytesIO(fixture_bytes))
    ws = wb["Golden Tours"]
    ws.append([None] * 18)
    buf = io.BytesIO()
    wb.save(buf)

    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = {"Body": io.BytesIO(buf.getvalue())}
    with patch("services.eval.regression.boto3.client", return_value=fake_s3):
        tours = _download_golden_tours()

    assert len(tours) == 1
