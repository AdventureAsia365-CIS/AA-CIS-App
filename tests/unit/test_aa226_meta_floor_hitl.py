"""AA-226: meta unrecoverable below floor must NOT reach gold — flag manual_check (HITL).
Integration over flag_fix_node with LLMClient patched. The node calls LLMClient().generate()
twice when meta stays under-band: once for the main field fix, once for the clue-guided
re-repair (_rerepair_meta). side_effect feeds both calls in order.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from services.content_generation import flag_fix_node as ff

_LEAD = "Trek valleys meet weavers rest at lodge "
def _meta(n):
    """Complete sentence of EXACTLY n chars: lead + filler + period."""
    return _LEAD + ("a" * (n - len(_LEAD) - 1)) + "."

def _resp(payload, cost=0.004):
    return SimpleNamespace(content=json.dumps(payload), cost_usd=cost,
                           model_used="haiku", fallback_used=False,
                           satellite_used=False)

def _state(seo=None, cur_meta=None):
    # brand_audit flags seo_meta so _should_fix + _build_fix_keys include it.
    return {
        "tour": {"country": "Nepal", "duration": "10 days"},
        "generated": {"name": "Annapurna Circuit", "seo_meta": cur_meta or _meta(132),
                      "seo_title": "Annapurna Circuit Trek"},
        "brand_audit_status": "flagged",
        "brand_audit_codes": ["META_TOO_SHORT"],
        "brand_audit_issues": ["seo_meta under 140 chars"],
        "model_tier": "haiku",
        "cost_usd": 0.0,
        "seo": seo if seo is not None else {"people_also_ask": ["best time to trek Annapurna"]},
    }

def _patch_llm(responses):
    inst = MagicMock()
    inst.generate.side_effect = responses
    return patch.object(ff, "LLMClient", return_value=inst)

def test_rerepair_recovers_in_band_no_hitl():
    """Main fix returns under-floor (132); clue re-repair returns in-band (148) -> accepted,
    no manual_check."""
    main = _resp({"seo_meta": _meta(132)})
    rerepair = _resp({"seo_meta": _meta(148)})
    with _patch_llm([main, rerepair]):
        out = ff.flag_fix_node(_state())
    assert len(out["generated"]["seo_meta"]) == 148
    assert out.get("brand_audit_status") != "manual_check"
    assert out["fix_pass_applied"] is True

def test_rerepair_still_under_floor_forces_hitl():
    """Both main fix and re-repair stay at 132 -> not accepted into gold -> manual_check."""
    main = _resp({"seo_meta": _meta(132)})
    rerepair = _resp({"seo_meta": _meta(132)})
    with _patch_llm([main, rerepair]):
        out = ff.flag_fix_node(_state())
    assert out["brand_audit_status"] == "manual_check"
    assert out["fix_pass_applied"] is True

def test_in_band_first_pass_no_rerepair_no_hitl():
    """Main fix already in band (148) -> only ONE LLM call, no manual_check."""
    main = _resp({"seo_meta": _meta(148)})
    inst = MagicMock()
    inst.generate.side_effect = [main]
    with patch.object(ff, "LLMClient", return_value=inst):
        out = ff.flag_fix_node(_state())
    assert len(out["generated"]["seo_meta"]) == 148
    assert out.get("brand_audit_status") != "manual_check"
    assert inst.generate.call_count == 1

def test_no_seo_context_still_flags_hitl():
    """No PAA/related clue available + re-repair fails -> still manual_check (no crash)."""
    main = _resp({"seo_meta": _meta(132)})
    rerepair = _resp({"seo_meta": _meta(132)})
    with _patch_llm([main, rerepair]):
        out = ff.flag_fix_node(_state(seo={}))
    assert out["brand_audit_status"] == "manual_check"
