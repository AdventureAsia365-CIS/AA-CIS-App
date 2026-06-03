"""
AA-167 — S3 Sonnet/Haiku model ID correctness tests.
"""
import json
from unittest.mock import MagicMock, patch

import planner
import ads
import lessons


class TestAA167ModelIDs:
    def test_sonnet_model_id_is_correct(self):
        assert planner.SONNET_MODEL_ID == "us.anthropic.claude-sonnet-4-5-20251001-v1:0"

    def test_haiku_model_id_ads_is_correct(self):
        assert ads.HAIKU_MODEL_ID == "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    def test_haiku_model_id_lessons_is_correct(self):
        assert lessons.HAIKU_MODEL_ID == "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    def test_sonnet_is_not_haiku(self):
        assert planner.SONNET_MODEL_ID != ads.HAIKU_MODEL_ID

    def test_skeleton_call_uses_sonnet(self):
        from models import CompactPacket, CalendarSkeleton, Week, Post

        skeleton = CalendarSkeleton(
            document_title="Test",
            weeks=[Week(week=1, posts=[
                Post(
                    title_topic="T", primary_keyword="kw", secondary_keywords=[],
                    search_intent="informational", word_count=1000, format="guide",
                    brief_outline=["A"], lead_magnet_cta="Download",
                )
            ])],
        )
        packet = CompactPacket(
            top_keywords=[], funnel_mix={"tofu": 20, "mofu": 60, "bofu": 20},
            cadence_weeks=12, posts_per_week=2, country="Vietnam", lesson_summary="",
        )

        mock_client = MagicMock()
        mock_client.exceptions.ThrottlingException = Exception
        mock_resp_body = MagicMock()
        mock_resp_body.read.return_value = json.dumps({
            "content": [{"text": json.dumps(skeleton.model_dump())}],
            "usage": {"input_tokens": 100, "output_tokens": 200},
        }).encode()
        mock_client.invoke_model.return_value = {"body": mock_resp_body}

        with patch("planner._bedrock_client", return_value=mock_client):
            planner.skeleton_call(packet)

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == planner.SONNET_MODEL_ID
        assert "sonnet" in call_kwargs["modelId"]

    def test_ads_call_uses_haiku(self):
        from models import AdsOutput, Campaign, AdGroup, CompactPacket

        ads_out = AdsOutput(campaigns=[
            Campaign(
                campaign_name="Test", objective="awareness",
                ad_groups=[AdGroup(
                    name="A", keywords=["kw"], headlines=["H"], descriptions=["D"],
                )],
            )
        ])
        packet = CompactPacket(
            top_keywords=[], funnel_mix={"tofu": 20, "mofu": 60, "bofu": 20},
            cadence_weeks=12, posts_per_week=2, country="Vietnam", lesson_summary="",
        )

        mock_client = MagicMock()
        mock_client.exceptions.ThrottlingException = Exception
        mock_resp_body = MagicMock()
        mock_resp_body.read.return_value = json.dumps({
            "content": [{"text": json.dumps(ads_out.model_dump())}],
            "usage": {"input_tokens": 50, "output_tokens": 80},
        }).encode()
        mock_client.invoke_model.return_value = {"body": mock_resp_body}

        with patch("ads._bedrock_client", return_value=mock_client):
            ads.generate_ads(packet)

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == ads.HAIKU_MODEL_ID
        assert "haiku" in call_kwargs["modelId"]
