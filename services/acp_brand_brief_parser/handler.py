import traceback

import boto3

from builder import build_rules_row
from db import upsert_brand_rules
from parser import parse_docx


def handler(event, context):
    """
    event = {
        "tenant_id": "atlas",
        "s3_bucket": "acp-bronze-867490540162",
        "s3_key": "brand-briefs/atlas/2026-05-20T12:00:00.docx"
    }
    """
    tenant_id = event["tenant_id"]
    s3_bucket = event["s3_bucket"]
    s3_key = event["s3_key"]
    local_path = f"/tmp/{tenant_id}.docx"

    try:
        s3 = boto3.client("s3")
        s3.download_file(s3_bucket, s3_key, local_path)
    except Exception as e:
        return {
            "status": "error",
            "tenant_id": tenant_id,
            "confidence": 0.0,
            "sections_parsed": 0,
            "warnings": [f"S3 download failed: {e}"],
            "version_id": None,
        }

    try:
        parsed = parse_docx(local_path)
    except Exception as e:
        return {
            "status": "error",
            "tenant_id": tenant_id,
            "confidence": 0.0,
            "sections_parsed": 0,
            "warnings": [f"Parse failed: {e}", traceback.format_exc()],
            "version_id": None,
        }

    sections_parsed = round(parsed.confidence * 8)
    warnings: list[str] = []

    if parsed.confidence < 0.6:
        warnings.append(
            f"Low confidence ({parsed.confidence:.2f}) — expected sections not found. DB write skipped."
        )
        return {
            "status": "low_confidence",
            "tenant_id": tenant_id,
            "confidence": parsed.confidence,
            "sections_parsed": sections_parsed,
            "warnings": warnings,
            "version_id": None,
        }

    try:
        row = build_rules_row(parsed, tenant_id, s3_key)
        version_id = upsert_brand_rules(row)
    except Exception as e:
        return {
            "status": "error",
            "tenant_id": tenant_id,
            "confidence": parsed.confidence,
            "sections_parsed": sections_parsed,
            "warnings": [f"DB write failed: {e}", traceback.format_exc()],
            "version_id": None,
        }

    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "confidence": parsed.confidence,
        "sections_parsed": sections_parsed,
        "warnings": warnings,
        "version_id": version_id,
    }
