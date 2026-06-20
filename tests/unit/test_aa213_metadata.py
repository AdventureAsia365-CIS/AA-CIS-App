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
