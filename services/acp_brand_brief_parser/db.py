import json
import os
import uuid
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras

from .models import BrandRulesRow


def _get_conn():
    dsn = os.environ["DATABASE_URL"]
    p = urlparse(dsn)
    return psycopg2.connect(
        host=p.hostname,
        port=p.port or 5432,
        user=p.username,
        password=p.password,
        dbname=p.path.lstrip("/"),
        sslmode="require",
    )


def upsert_brand_rules(row: BrandRulesRow) -> str:
    version_id = str(uuid.uuid4())
    snapshot = json.dumps({
        "brand_type": row.brand_type,
        "core_idea": row.core_idea,
        "target_markets": row.target_markets,
        "customer_segment": row.customer_segment,
        "customer_mindset": row.customer_mindset,
        "voice_examples": row.voice_examples,
        "style_guide": row.style_guide,
        "forbidden_words": row.forbidden_words,
        "system_prompt": row.system_prompt,
        "source_docx_s3_key": row.source_docx_s3_key,
        "updated_at": row.updated_at,
    })

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shared.tenant_brand_rules (
                    tenant_id, brand_type, core_idea, target_markets,
                    customer_segment, customer_mindset, voice_examples,
                    style_guide, forbidden_words, system_prompt,
                    source_docx_s3_key, updated_at
                ) VALUES (
                    %(tenant_id)s, %(brand_type)s, %(core_idea)s, %(target_markets)s,
                    %(customer_segment)s, %(customer_mindset)s, %(voice_examples)s,
                    %(style_guide)s, %(forbidden_words)s, %(system_prompt)s,
                    %(source_docx_s3_key)s, NOW()
                )
                ON CONFLICT (tenant_id) DO UPDATE SET
                    brand_type = EXCLUDED.brand_type,
                    core_idea = EXCLUDED.core_idea,
                    target_markets = EXCLUDED.target_markets,
                    customer_segment = EXCLUDED.customer_segment,
                    customer_mindset = EXCLUDED.customer_mindset,
                    voice_examples = EXCLUDED.voice_examples,
                    style_guide = EXCLUDED.style_guide,
                    forbidden_words = EXCLUDED.forbidden_words,
                    system_prompt = EXCLUDED.system_prompt,
                    source_docx_s3_key = EXCLUDED.source_docx_s3_key,
                    updated_at = NOW()
            """, {
                "tenant_id": row.tenant_id,
                "brand_type": row.brand_type,
                "core_idea": row.core_idea,
                "target_markets": row.target_markets,
                "customer_segment": row.customer_segment,
                "customer_mindset": row.customer_mindset,
                "voice_examples": psycopg2.extras.Json(row.voice_examples),
                "style_guide": row.style_guide,
                "forbidden_words": row.forbidden_words,
                "system_prompt": row.system_prompt,
                "source_docx_s3_key": row.source_docx_s3_key,
            })

            cur.execute("""
                INSERT INTO shared.tenant_brand_rule_versions (
                    id, tenant_id, snapshot, source_docx_s3_key, source_type, created_by
                ) VALUES (
                    %(id)s, %(tenant_id)s, %(snapshot)s, %(s3_key)s, 'docx_parse', 'lambda'
                )
            """, {
                "id": version_id,
                "tenant_id": row.tenant_id,
                "snapshot": psycopg2.extras.Json(json.loads(snapshot)),
                "s3_key": row.source_docx_s3_key,
            })

        conn.commit()

    return version_id
