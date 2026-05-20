import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import planner
from models import CalendarSkeleton, CompactPacket


def _make_run_context(n_keywords=25):
    keywords = {}
    for i in range(n_keywords):
        keywords[f"keyword_{i}"] = {
            "vol_m1": i * 10,
            "vol_m2": i * 12,
            "competition": "medium",
            "cpc": 1.5,
            "intent": "informational",
        }
    return {
        "s2_keyword_research": {"keywords": keywords},
        "s2_visibility_report": {},
        "s1_keywords_used": [],
        "brand_brief": {},
    }


class TestBuildCompactPacket:
    def test_top_18_selected(self):
        ctx = _make_run_context(25)
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "no lessons")
        assert len(packet.top_keywords) == 18

    def test_fewer_than_18_keywords(self):
        ctx = _make_run_context(10)
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "no lessons")
        assert len(packet.top_keywords) == 10

    def test_sorted_by_max_vol(self):
        ctx = _make_run_context(25)
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "no lessons")
        vols = [k["vol"] for k in packet.top_keywords]
        assert vols == sorted(vols, reverse=True)

    def test_default_funnel_mix(self):
        ctx = _make_run_context(5)
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "no lessons")
        assert packet.funnel_mix == {"tofu": 20, "mofu": 60, "bofu": 20}

    def test_custom_funnel_mix_from_brand_brief(self):
        ctx = _make_run_context(5)
        ctx["brand_brief"] = {"funnel_mix": {"tofu": 10, "mofu": 70, "bofu": 20}}
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "no lessons")
        assert packet.funnel_mix == {"tofu": 10, "mofu": 70, "bofu": 20}

    def test_default_cadence(self):
        ctx = _make_run_context(5)
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "no lessons")
        assert packet.cadence_weeks == 12
        assert packet.posts_per_week == 2

    def test_country_preserved(self):
        ctx = _make_run_context(5)
        packet = planner.build_compact_packet(ctx, {}, "Sri Lanka", "no lessons")
        assert packet.country == "Sri Lanka"

    def test_lesson_summary_passed_through(self):
        ctx = _make_run_context(5)
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "some lessons here")
        assert packet.lesson_summary == "some lessons here"

    def test_empty_keywords_returns_empty_top(self):
        ctx = {
            "s2_keyword_research": {"keywords": {}},
            "s2_visibility_report": {},
            "s1_keywords_used": [],
            "brand_brief": {},
        }
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "")
        assert packet.top_keywords == []

    def test_vol_uses_max_of_two_markets(self):
        ctx = {
            "s2_keyword_research": {"keywords": {
                "kw_a": {"vol_m1": 100, "vol_m2": 500},
                "kw_b": {"vol_m1": 300, "vol_m2": 200},
            }},
            "s2_visibility_report": {},
            "s1_keywords_used": [],
            "brand_brief": {},
        }
        packet = planner.build_compact_packet(ctx, {}, "Vietnam", "")
        assert packet.top_keywords[0]["keyword"] == "kw_a"
        assert packet.top_keywords[0]["vol"] == 500
