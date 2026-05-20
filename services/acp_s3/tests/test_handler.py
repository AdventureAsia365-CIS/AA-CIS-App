import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from unittest.mock import MagicMock, patch, call

import handler
from models import (
    AdGroup, AdsOutput, CalendarSkeleton, Campaign, LessonUpdateOutput, Post, Week,
)


def _make_skeleton():
    return CalendarSkeleton(
        document_title="Vietnam 12-Week Content Calendar",
        weeks=[
            Week(week=1, posts=[
                Post(
                    title_topic="Best Vietnam Adventure Tours",
                    primary_keyword="vietnam adventure tours",
                    secondary_keywords=["vietnam trekking"],
                    search_intent="informational",
                    word_count=1200,
                    format="guide",
                    brief_outline=["Introduction", "Top picks", "Booking tips"],
                    lead_magnet_cta="Download free itinerary",
                )
            ])
        ],
    )


def _make_ads_output():
    return AdsOutput(campaigns=[
        Campaign(
            campaign_name="Vietnam TOFU",
            objective="awareness",
            ad_groups=[
                AdGroup(
                    name="Adventure",
                    keywords=["vietnam adventure tours"],
                    headlines=["Explore Vietnam"],
                    descriptions=["Luxury adventures await."],
                )
            ],
        )
    ])


class TestHandler:
    def test_missing_run_id_returns_error(self):
        result = handler.handler({"tenant_id": "atlas"}, None)
        assert result["status"] == "error"
        assert "run_id" in result["error"]

    def test_missing_tenant_id_returns_error(self):
        result = handler.handler({"run_id": "some-uuid"}, None)
        assert result["status"] == "error"

    def test_successful_flow(self):
        skeleton = _make_skeleton()
        ads_out = _make_ads_output()
        lesson_out = LessonUpdateOutput(
            job_lessons=["l1"], root_lessons_append=[], system_promotions=[]
        )
        run_context = {
            "s2_keyword_research": {"keywords": {
                "vietnam adventure tours": {
                    "vol_m1": 1000, "vol_m2": 1200,
                    "competition": "medium", "cpc": 2.0, "intent": "commercial",
                },
            }},
            "s2_visibility_report": {},
            "s1_keywords_used": [],
            "brand_brief": {},
        }

        with patch("handler._get_db_conn") as mock_db, \
             patch("handler._read_run_inputs") as mock_read, \
             patch("handler._lessons") as mock_les, \
             patch("handler._planner") as mock_plan, \
             patch("handler._ads") as mock_ads, \
             patch("handler._validators") as mock_val, \
             patch("handler._write_outputs") as mock_write, \
             patch("handler._create_hitl_gate2") as mock_hitl, \
             patch("handler._emit_eventbridge") as mock_eb:

            mock_conn = MagicMock()
            mock_db.return_value = mock_conn

            mock_read.return_value = (run_context, {"system_prompt": "", "style_guide": ""}, "Vietnam")
            mock_les.read_lessons.return_value = "lesson summary"

            mock_packet = MagicMock(
                funnel_mix={"tofu": 20, "mofu": 60, "bofu": 20},
                country="Vietnam",
            )
            mock_plan.build_compact_packet.return_value = mock_packet
            mock_plan.skeleton_call.return_value = (skeleton, 100, 200)
            mock_plan.expand_call.return_value = (
                "### Week 1\nPrimary Keyword: vietnam adventure tours\nLead Magnet CTA: Download",
                50, 100,
            )
            mock_plan._SONNET = "us.anthropic.claude-sonnet-4-5"
            mock_ads.generate_ads.return_value = (ads_out, 80, 120)
            mock_ads.upload_ads_pdf.return_value = "acp/s3/ads-plans/atlas/run1/ads_plan.pdf"
            mock_ads._HAIKU = "us.anthropic.claude-haiku-4-5"
            mock_val.run_all.return_value = []
            mock_les.lesson_update_call.return_value = (lesson_out, 30, 60)
            mock_write.return_value = ("cal-uuid-1", "ads-uuid-1")

            result = handler.handler({"run_id": "run-1", "tenant_id": "atlas"}, None)

        assert result["status"] == "completed"
        assert result["run_id"] == "run-1"
        assert result["calendar_id"] == "cal-uuid-1"
        assert result["ads_plan_id"] == "ads-uuid-1"
        mock_hitl.assert_called_once_with(mock_conn, "run-1")
        mock_conn.commit.assert_called_once()
        mock_eb.assert_called_once_with("run-1", "atlas")

    def test_validation_errors_included_in_result(self):
        skeleton = _make_skeleton()
        ads_out = _make_ads_output()
        lesson_out = LessonUpdateOutput(job_lessons=[], root_lessons_append=[], system_promotions=[])

        with patch("handler._get_db_conn") as mock_db, \
             patch("handler._read_run_inputs") as mock_read, \
             patch("handler._lessons") as mock_les, \
             patch("handler._planner") as mock_plan, \
             patch("handler._ads") as mock_ads, \
             patch("handler._validators") as mock_val, \
             patch("handler._write_outputs") as mock_write, \
             patch("handler._create_hitl_gate2"), \
             patch("handler._emit_eventbridge"):

            mock_db.return_value = MagicMock()
            mock_read.return_value = ({}, {}, "Vietnam")
            mock_les.read_lessons.return_value = ""
            mock_plan.build_compact_packet.return_value = MagicMock(
                funnel_mix={"tofu": 20, "mofu": 60, "bofu": 20}, country="Vietnam"
            )
            mock_plan.skeleton_call.return_value = (skeleton, 0, 0)
            mock_plan.expand_call.return_value = ("no structure", 0, 0)
            mock_plan._SONNET = "us.anthropic.claude-sonnet-4-5"
            mock_ads.generate_ads.return_value = (ads_out, 0, 0)
            mock_ads.upload_ads_pdf.return_value = "key"
            mock_ads._HAIKU = "us.anthropic.claude-haiku-4-5"
            mock_val.run_all.return_value = ["week_structure: missing", "lead_magnet_cta: missing"]
            mock_les.lesson_update_call.return_value = (lesson_out, 0, 0)
            mock_write.return_value = ("cal-1", "ads-1")

            result = handler.handler({"run_id": "run-1", "tenant_id": "atlas"}, None)

        assert result["status"] == "completed"
        assert len(result["validation_errors"]) == 2

    def test_db_error_returns_error_status(self):
        with patch("handler._get_db_conn") as mock_db:
            mock_db.side_effect = Exception("DB connection refused")
            result = handler.handler({"run_id": "run-1", "tenant_id": "atlas"}, None)

        assert result["status"] == "error"
        assert "DB connection refused" in result["error"]

    def test_rollback_called_on_error(self):
        mock_conn = MagicMock()
        with patch("handler._get_db_conn", return_value=mock_conn), \
             patch("handler._read_run_inputs", side_effect=ValueError("missing context")):
            result = handler.handler({"run_id": "run-1", "tenant_id": "atlas"}, None)

        assert result["status"] == "error"
        mock_conn.rollback.assert_called_once()
