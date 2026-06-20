import pytest
from services.content_generation import graph as g
from services.content_generation.graph import revalidate_node, build_graph

def _base_state(**over):
    s = {
        "generated": {"name": "X", "summary": "y", "itineraries": "Day 1 -- Real Place",
                      "highlights": ["a","b","c","d"], "seo_title": "t", "seo_meta": "m"*150},
        "quality_score": 9.0, "fix_pass_applied": False, "brand_audit_status": "pass",
        "failure_codes": [], "sub_scores": {}, "feedback": "",
    }
    s.update(over); return s

def test_passthrough_when_no_fix():
    # fix_pass_applied=False -> revalidate khong chay, status giu nguyen, ran=False
    out = revalidate_node(_base_state(fix_pass_applied=False, brand_audit_status="pass"))
    assert out["revalidate_ran"] is False
    assert out["brand_audit_status"] == "pass"

def test_passthrough_unfixed_flagged_stays_blocked(monkeypatch):
    # flagged NHUNG chua sua -> passthrough, status van "flagged" (gate AA-211 chan, revalidate khong cuu)
    out = revalidate_node(_base_state(fix_pass_applied=False, brand_audit_status="flagged"))
    assert out["revalidate_ran"] is False
    assert out["brand_audit_status"] == "flagged"

def test_fixed_when_repair_passes(monkeypatch):
    # fix_pass_applied=True + re-validate/judge cho score cao -> status "fixed", passed True
    monkeypatch.setattr(g, "validate_node", lambda st: {**st, "quality_score": 9.0, "brand_audit_status": ""})
    monkeypatch.setattr(g, "judge_node", lambda st: {**st, "quality_score": 9.0})
    out = revalidate_node(_base_state(fix_pass_applied=True))
    assert out["revalidate_ran"] is True
    assert out["revalidate_passed"] is True
    assert out["brand_audit_status"] == "fixed"

def test_manual_check_when_repair_regresses(monkeypatch):
    # fix_pass_applied=True nhung re-validate cho score thap -> status "manual_check", passed False
    monkeypatch.setattr(g, "validate_node", lambda st: {**st, "quality_score": 4.0, "brand_audit_status": ""})
    monkeypatch.setattr(g, "judge_node", lambda st: {**st, "quality_score": 4.0})
    out = revalidate_node(_base_state(fix_pass_applied=True))
    assert out["revalidate_ran"] is True
    assert out["revalidate_passed"] is False
    assert out["brand_audit_status"] == "manual_check"

def test_compiled_graph_has_revalidate_node_and_edges():
    # qua compiled graph THAT — chan LangGraph strip / wiring sai
    compiled = build_graph()
    gobj = compiled.get_graph()
    node_ids = set(gobj.nodes.keys())
    assert "revalidate" in node_ids
    edges = {(e.source, e.target) for e in gobj.edges}
    assert ("flag_fix", "revalidate") in edges
    assert ("revalidate", "__end__") in edges or any(s=="revalidate" for s,_ in edges)
    # flag_fix KHONG con noi thang END
    assert ("flag_fix", "__end__") not in edges
