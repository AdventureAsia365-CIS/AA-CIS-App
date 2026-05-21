import json
import os
import uuid
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from models import BrandRulesRow


def upsert_brand_rules(row: BrandRulesRow) -> str:
    db_url = os.environ.get("DATABASE_URL")
    conn = psycopg2.connect(db_url, sslmode="require")
    version_id = str(uuid.uuid4())
    try:
        with conn:
            with conn.cursor() as cur:
                # Check existing row
                cur.execute(
                    "SELECT id FROM shared.tenant_brand_rules WHERE tenant_id = %s",
                    (row.tenant_id,)
                )
                existing = cur.fetchone()

                voice_json = json.dumps(
                    row.voice_examples if isinstance(row.voice_examples, dict)
                    else row.voice_examples.model_dump()
                )
                forbidden_json = json.dumps(row.forbidden_words)
                target_markets_arr = row.target_markets  # text[] — pass as list

                if existing:
                    cur.execute("""
                        UPDATE shared.tenant_brand_rules SET
                            brand_type = %s,
                            core_idea = %s,
                            customer_segment = %s,
                            customer_mindset = %s,
                            voice_examples = %s::jsonb,
                            style_guide = %s,
                            forbidden_words = %s::jsonb,
                            system_prompt = %s,
                            source_docx_s3_key = %s,
                            target_markets = %s,
                            updated_at = NOW()
                        WHERE tenant_id = %s
                        RETURNING id
                    """, (
                        row.brand_type, row.core_idea,
                        row.customer_segment, row.customer_mindset,
                        voice_json, row.style_guide,
                        forbidden_json, row.system_prompt,
                        row.source_docx_s3_key, target_markets_arr,
                        row.tenant_id
                    ))
                    record_id = cur.fetchone()[0]
                else:
                    cur.execute("""
                        INSERT INTO shared.tenant_brand_rules
                            (tenant_id, brand_type, core_idea,
                             customer_segment, customer_mindset,
                             voice_examples, style_guide, forbidden_words,
                             system_prompt, source_docx_s3_key, target_markets)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s)
                        RETURNING id
                    """, (
                        row.tenant_id, row.brand_type, row.core_idea,
                        row.customer_segment, row.customer_mindset,
                        voice_json, row.style_guide,
                        forbidden_json, row.system_prompt,
                        row.source_docx_s3_key, target_markets_arr
                    ))
                    record_id = cur.fetchone()[0]

                # Insert version snapshot
                snapshot = {
                    "brand_type": row.brand_type,
                    "core_idea": row.core_idea,
                    "customer_segment": row.customer_segment,
                    "customer_mindset": row.customer_mindset,
                    "voice_examples": json.loads(voice_json),
                    "style_guide": row.style_guide,
                    "forbidden_words": row.forbidden_words,
                    "system_prompt": row.system_prompt,
                    "target_markets": row.target_markets,
                }
                cur.execute("""
                    INSERT INTO shared.tenant_brand_rule_versions
                        (version_id, tenant_id, snapshot, source_docx_s3_key, source_type, created_by)
                    VALUES (%s, %s, %s::jsonb, %s, 'docx_parse', 'lambda')
                """, (
                    version_id, row.tenant_id,
                    json.dumps(snapshot), row.source_docx_s3_key
                ))
    finally:
        conn.close()
    return version_id
