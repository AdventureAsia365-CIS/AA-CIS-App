"""
services.acp_angle_gate.brand_audience — T8 workflow step 3: "Tự động lấy fixed brand audience".

STEP0 (docs/claude_audit/AA-449-00-step0-t8-angle-gate-investigation.md §6) found the real
source: shared.tenant_brand_rules.customer_segment/customer_mindset (migration 018, AA-85/AA-82)
— already populated per-tenant since T0 Brand Setup (docx-parse or manual seed), but NOT exposed
by any existing tenant-facing endpoint (BrandTab.tsx's BrandData interface only carries
system_prompt/style_guide/forbidden_words — the audience data is baked as prose INSIDE
system_prompt, not available as a separate field). This is the first tenant-facing read of these
2 columns directly.

Deliberately reads customer_segment + customer_mindset only (not the full system_prompt, which
also carries tone/style/forbidden-words guidance irrelevant to "who is the audience") and not
brand_type/core_idea (STEP0 didn't identify those as part of "audience" specifically — segment =
who they are, mindset = what they think/want, which is what an angle-generation prompt actually
needs to write TO someone, not a general brand description)."""
from __future__ import annotations

from typing import Optional, TypedDict
from uuid import UUID


class BrandAudience(TypedDict):
    customer_segment: Optional[str]
    customer_mindset: Optional[str]


async def fetch_brand_audience(tenant_id: UUID, pool) -> BrandAudience:
    """Returns {} fields as None if the tenant has no active tenant_brand_rules row yet, or has
    one but never had these 2 columns populated (T0 Brand Setup done via manual system_prompt
    entry only, not a docx-parse upload) — caller decides how to handle a missing audience
    (generate.py falls back to a generic placeholder, doesn't crash — see that module)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT customer_segment, customer_mindset
            FROM shared.tenant_brand_rules
            WHERE tenant_id = $1 AND is_active = true
            ORDER BY version DESC
            LIMIT 1
            """,
            tenant_id,
        )
    if row is None:
        return {"customer_segment": None, "customer_mindset": None}
    return {"customer_segment": row["customer_segment"], "customer_mindset": row["customer_mindset"]}


__all__ = ["BrandAudience", "fetch_brand_audience"]
