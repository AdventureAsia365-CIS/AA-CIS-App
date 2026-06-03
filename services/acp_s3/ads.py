"""
Google Ads generator: Bedrock Haiku call + PDF generation via fpdf2 + S3 upload.
"""
import io
import json
import os
import time

import boto3
from fpdf import FPDF

from models import AdsOutput, CompactPacket

HAIKU_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_BEDROCK_REGION = "us-west-1"
_S3_BUCKET = os.environ.get("S3_BRONZE_BUCKET", "aa-cis-bronze-867490540162")

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _read_prompt(filename: str) -> str:
    with open(os.path.join(_PROMPT_DIR, filename)) as f:
        return f.read()


def _bedrock_client():
    return boto3.client("bedrock-runtime", region_name=_BEDROCK_REGION)


def _invoke(client, model_id: str, prompt: str, max_tokens: int = 4096) -> tuple[str, int, int]:
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    for attempt in range(3):
        try:
            resp = client.invoke_model(modelId=model_id, body=body)
            parsed = json.loads(resp["body"].read())
            text = parsed["content"][0]["text"]
            usage = parsed.get("usage", {})
            return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        except client.exceptions.ThrottlingException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def generate_ads(packet: CompactPacket) -> tuple[AdsOutput, int, int]:
    """Step 5a: Bedrock Haiku ads call. Returns (AdsOutput, in_tok, out_tok)."""
    ads_prompt = _read_prompt("google_ads_prompt.md")
    prompt = f"{ads_prompt}\n\n## Compact Packet\n```json\n{json.dumps(packet.model_dump(), indent=2)}\n```"

    client = _bedrock_client()
    text, in_tok, out_tok = _invoke(client, HAIKU_MODEL_ID, prompt)

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    data = json.loads(text)
    return AdsOutput(**data), in_tok, out_tok


def _safe_text(text: str) -> str:
    """Replace non-latin-1 characters for fpdf2 built-in fonts."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _build_pdf(ads: AdsOutput, tenant_id: str, country: str) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _safe_text(f"Google Ads Plan - {country}"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe_text(f"Tenant: {tenant_id}"), ln=True)
    pdf.ln(4)

    for campaign in ads.campaigns:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, _safe_text(f"Campaign: {campaign.campaign_name}"), ln=True)
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, _safe_text(f"Objective: {campaign.objective}"), ln=True)
        pdf.ln(2)

        for ag in campaign.ad_groups:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, _safe_text(f"  Ad Group: {ag.name}"), ln=True)

            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, _safe_text(f"  Keywords: {', '.join(ag.keywords)}"))

            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, "  Headlines:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            for h in ag.headlines:
                pdf.cell(0, 5, _safe_text(f"    - {h}"), ln=True)

            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, "  Descriptions:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            for d in ag.descriptions:
                pdf.multi_cell(0, 5, _safe_text(f"    - {d}"))
            pdf.ln(3)

        pdf.ln(4)

    return bytes(pdf.output())


def upload_ads_pdf(ads: AdsOutput, tenant_id: str, country: str, run_id: str) -> str:
    """Generate PDF, upload to S3, return s3_key. Returns empty string on PDF error."""
    try:
        pdf_bytes = _build_pdf(ads, tenant_id, country)
    except Exception:
        return ""
    s3_key = f"acp/s3/ads-plans/{tenant_id}/{run_id}/ads_plan.pdf"
    s3 = boto3.client("s3", region_name=_BEDROCK_REGION)
    s3.upload_fileobj(
        io.BytesIO(pdf_bytes),
        _S3_BUCKET,
        s3_key,
        ExtraArgs={"ContentType": "application/pdf"},
    )
    return s3_key
