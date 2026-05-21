import json
from unittest.mock import MagicMock, patch

import ads
from models import AdGroup, AdsOutput, Campaign, CompactPacket


def _make_packet():
    return CompactPacket(
        top_keywords=[
            {"keyword": "vietnam adventure tours", "vol": 1000,
             "competition": "medium", "cpc": 2.5, "intent": "commercial"},
            {"keyword": "vietnam trekking packages", "vol": 800,
             "competition": "low", "cpc": 1.8, "intent": "informational"},
        ],
        funnel_mix={"tofu": 20, "mofu": 60, "bofu": 20},
        cadence_weeks=12,
        posts_per_week=2,
        country="Vietnam",
        lesson_summary="",
    )


def _make_ads_output():
    return AdsOutput(campaigns=[
        Campaign(
            campaign_name="Vietnam TOFU Awareness",
            objective="awareness",
            ad_groups=[
                AdGroup(
                    name="Adventure Tours",
                    keywords=["vietnam adventure tours", "+vietnam +adventure"],
                    headlines=["Explore Vietnam in Style", "Luxury Vietnam Tours"],
                    descriptions=["Tailor-made Vietnam adventures for discerning travelers."],
                )
            ],
        )
    ])


class TestGenerateAds:
    def test_returns_ads_output_model(self):
        ads_out = _make_ads_output()
        mock_response = json.dumps(ads_out.model_dump())

        with patch("ads._bedrock_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_resp_body = MagicMock()
            mock_resp_body.read.return_value = json.dumps({
                "content": [{"text": mock_response}],
                "usage": {"input_tokens": 100, "output_tokens": 200},
            }).encode()
            mock_client.invoke_model.return_value = {"body": mock_resp_body}
            mock_client.exceptions.ThrottlingException = Exception

            result, in_tok, out_tok = ads.generate_ads(_make_packet())

        assert isinstance(result, AdsOutput)
        assert len(result.campaigns) == 1
        assert in_tok == 100
        assert out_tok == 200

    def test_strips_markdown_fences(self):
        ads_out = _make_ads_output()
        fenced = f"```json\n{json.dumps(ads_out.model_dump())}\n```"

        with patch("ads._bedrock_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_resp_body = MagicMock()
            mock_resp_body.read.return_value = json.dumps({
                "content": [{"text": fenced}],
                "usage": {"input_tokens": 50, "output_tokens": 80},
            }).encode()
            mock_client.invoke_model.return_value = {"body": mock_resp_body}
            mock_client.exceptions.ThrottlingException = Exception

            result, _, _ = ads.generate_ads(_make_packet())

        assert isinstance(result, AdsOutput)


class TestBuildPdf:
    def test_returns_bytes(self):
        ads_out = _make_ads_output()
        pdf_bytes = ads._build_pdf(ads_out, "atlas", "Vietnam")
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_pdf_header(self):
        ads_out = _make_ads_output()
        pdf_bytes = ads._build_pdf(ads_out, "atlas", "Vietnam")
        # PDF magic bytes
        assert pdf_bytes[:4] == b"%PDF"
