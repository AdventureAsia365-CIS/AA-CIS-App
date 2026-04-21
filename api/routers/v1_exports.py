from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
import asyncpg, boto3, json, uuid, os
from api.routers.auth import verify_jwt

router = APIRouter(prefix="/v1/exports", tags=["B2B Exports"])
security = HTTPBearer()

S3_BUCKET = os.environ.get("S3_GOLD_BUCKET", "aa-cis-gold-867490540162")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-1")

def get_tenant(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        return verify_jwt(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

class ExportRequest(BaseModel):
    format: str = "json"
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    min_quality: Optional[float] = None

@router.post("")
async def create_export(
    body: ExportRequest,
    request: Request,
    tenant=Depends(get_tenant),
):
    tenant_id = tenant["sub"]
    pool = request.app.state.pool

    if body.format not in ("json", "csv", "xml"):
        raise HTTPException(status_code=400, detail="format must be json, csv, or xml")

    conditions = ["tenant_id = $1"]
    params = [tenant_id]

    if body.date_from:
        params.append(body.date_from)
        conditions.append(f"published_at >= ${len(params)}")
    if body.date_to:
        params.append(body.date_to)
        conditions.append(f"published_at <= ${len(params)}")
    if body.min_quality:
        params.append(body.min_quality)
        conditions.append(f"quality_score >= ${len(params)}")

    where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, tour_id, aa_name, aa_subtitle, aa_summary,
                   aa_description, aa_highlights, aa_itineraries,
                   mobile_card_text, seo_title, seo_meta,
                   seo_keywords_used, og_tags, quality_score, published_at
            FROM gold_aa_internal.published_tours
            {where}
            ORDER BY published_at DESC
        """, *params)

    if not rows:
        raise HTTPException(status_code=404, detail="No tours found for export criteria")

    tours = [dict(r) for r in rows]
    for t in tours:
        if t.get("published_at"):
            t["published_at"] = t["published_at"].isoformat()
        for f in ("aa_highlights", "seo_keywords_used", "og_tags"):
            if t.get(f) and not isinstance(t[f], str):
                t[f] = list(t[f]) if hasattr(t[f], '__iter__') else t[f]

    export_id = str(uuid.uuid4())
    row_id = str(uuid.uuid4())
    s3_key = f"exports/{tenant_id}/{export_id}.{body.format}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)

    if body.format == "json":
        content = json.dumps({"export_id": export_id, "tenant_id": tenant_id,
                              "total": len(tours), "data": tours}, indent=2, default=str)
        content_type = "application/json"
    elif body.format == "csv":
        import csv, io
        buf = io.StringIO()
        if tours:
            writer = csv.DictWriter(buf, fieldnames=tours[0].keys())
            writer.writeheader()
            writer.writerows(tours)
        content = buf.getvalue()
        content_type = "text/csv"
    else:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<tours>"]
        for t in tours:
            lines.append("  <tour>")
            for k, v in t.items():
                lines.append(f"    <{k}>{v}</{k}>")
            lines.append("  </tour>")
        lines.append("</tours>")
        content = "\n".join(lines)
        content_type = "application/xml"

    file_size_kb = len(content.encode("utf-8")) // 1024 or 1

    # Upload S3
    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=content.encode("utf-8"),
        ContentType=content_type,
    )

    signed_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": s3_key},
        ExpiresIn=604800,
    )

    filter_params = {}
    if body.date_from: filter_params["date_from"] = body.date_from
    if body.date_to: filter_params["date_to"] = body.date_to
    if body.min_quality: filter_params["min_quality"] = body.min_quality

    # Log to DB — match actual schema
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gold_aa_internal.content_exports
                (id, tenant_id, export_id, format, filter_params,
                 s3_path, signed_url, total_tours, file_size_kb,
                 status, expires_at, created_at, completed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        """, row_id, tenant_id, export_id, body.format,
            json.dumps(filter_params), s3_key, signed_url,
            len(tours), file_size_kb, "completed",
            expires_at, now, now)

    return {
        "export_id": export_id,
        "format": body.format,
        "tour_count": len(tours),
        "download_url": signed_url,
        "expires_at": expires_at.isoformat(),
        "s3_key": s3_key,
    }
