from api.routers.admin_pipeline import _build_generated_metadata

def _md(**over):
    res = {"quality_score": 8.0, "fallback_used": True,
           "revalidate_ran": True, "revalidate_passed": True}
    res.update(over.pop("result_over", {}))
    return _build_generated_metadata(
        res, brand_rule_id="r", brand_name="b", seo_mode="standard",
        model_used="m", llm_cost_usd=0.0, dataforseo_used=False,
        batch_id=over.get("batch_id", "verify-s70"))

def test_score_overall_fallback_batch_persisted():
    md = _md()
    assert md["score_overall"] == 8.0
    assert md["fallback_used"] is True
    assert md["batch_id"] == "verify-s70"
    assert md["revalidate_ran"] is True
    assert md["revalidate_passed"] is True

def test_fallback_defaults_false_when_absent():
    md = _build_generated_metadata(
        {"quality_score": 7.0}, brand_rule_id="r", brand_name="b", seo_mode="x",
        model_used="m", llm_cost_usd=0.0, dataforseo_used=False)
    assert md["fallback_used"] is False
    assert md["batch_id"] is None
    assert md["revalidate_ran"] is False

def test_judge_block_still_merged_regression():
    md = _build_generated_metadata(
        {"quality_score": 9.0, "judge_brand_fit": 8.0, "judge_score": 7.0,
         "judge_cross_brand_distinct": 7.0, "judge_mission_present": True, "judge_feedback": "ok"},
        brand_rule_id="r", brand_name="b", seo_mode="x",
        model_used="m", llm_cost_usd=0.0, dataforseo_used=False)
    assert md["judge"]["judge_score"] == 7.0
    assert md["judge"]["brand_fit"] == 8.0


# ── AA-353: itinerary_compression block ──────────────────────────────────────

def test_itinerary_compression_omitted_when_no_day_ratios():
    md = _build_generated_metadata(
        {"quality_score": 8.0}, brand_rule_id="r", brand_name="b", seo_mode="x",
        model_used="m", llm_cost_usd=0.0, dataforseo_used=False)
    assert "itinerary_compression" not in md


def test_itinerary_compression_persisted_all_in_clamp():
    md = _build_generated_metadata(
        {"quality_score": 8.0, "itinerary_day_ratios": [
            {"day": 1, "source_words": 100, "actual_words": 95, "ratio": 0.95, "nudged": False},
            {"day": 2, "source_words": 200, "actual_words": 210, "ratio": 1.05, "nudged": False},
        ]},
        brand_rule_id="r", brand_name="b", seo_mode="x",
        model_used="m", llm_cost_usd=0.0, dataforseo_used=False)
    comp = md["itinerary_compression"]
    assert len(comp["day_ratios"]) == 2
    assert comp["nudged_day_count"] == 0
    assert comp["violation_day_count"] == 0
    assert comp["still_violating_after_nudge"] == []


def test_itinerary_compression_tracks_nudged_and_still_violating():
    md = _build_generated_metadata(
        {"quality_score": 8.0, "itinerary_day_ratios": [
            {"day": 1, "source_words": 100, "actual_words": 95, "ratio": 0.95, "nudged": False},
            {"day": 2, "source_words": 200, "actual_words": 40, "ratio": 0.2, "nudged": True,
             "actual_words_after_nudge": 60, "ratio_after_nudge": 0.3},
        ]},
        brand_rule_id="r", brand_name="b", seo_mode="x",
        model_used="m", llm_cost_usd=0.0, dataforseo_used=False)
    comp = md["itinerary_compression"]
    assert comp["nudged_day_count"] == 1
    assert comp["violation_day_count"] == 1
    assert comp["still_violating_after_nudge"] == [2]
