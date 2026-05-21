"""
CMS publish queue processor.
Called async (fire-and-forget) after Gate 3 approve.
Fetches CMS credentials from Secrets Manager, pushes draft to WordPress.
"""
import json
import logging

import boto3

from .base import BlogContent
from .wordpress import WordPressAdapter

logger = logging.getLogger(__name__)

_SM_REGION = "us-west-1"


def _get_cms_creds(secret_key: str) -> dict:
    client = boto3.client("secretsmanager", region_name=_SM_REGION)
    return json.loads(client.get_secret_value(SecretId=secret_key)["SecretString"])


async def publish_draft_to_cms(pool, queue_id: str, draft_id: str,
                                tenant_id: str, cms_secret_key: str) -> bool:
    """
    Fetch draft → build BlogContent → push to WordPress as draft.
    Updates acp_cms_publish_queue + blog_drafts.cms_publish_status.
    Returns True on success, False on error (never raises).
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE acp_shared.acp_cms_publish_queue SET status='processing', processed_at=NOW() WHERE queue_id=$1",
            queue_id,
        )

        try:
            draft = await conn.fetchrow(
                "SELECT title, content_md, slug, seo_title, seo_meta FROM acp_silver_s4.blog_drafts WHERE draft_id=$1::uuid",
                draft_id,
            )
            if not draft:
                raise ValueError(f"draft {draft_id} not found")

            creds = _get_cms_creds(cms_secret_key)
            adapter = WordPressAdapter(
                wp_url=creds["wp_url"],
                username=creds["username"],
                app_password=creds["app_password"],
            )

            content = BlogContent(
                title=draft["title"],
                content_html=draft["content_md"] or "",
                slug=draft["slug"] or "",
                seo_title=draft["seo_title"] or draft["title"],
                seo_meta=draft["seo_meta"] or "",
            )

            result = await adapter.create_post(content)

            await conn.execute(
                "UPDATE acp_shared.acp_cms_publish_queue SET status='published', wp_post_id=$2, wp_post_url=$3 WHERE queue_id=$1",
                queue_id, result.post_id, result.post_url,
            )
            await conn.execute(
                "UPDATE acp_silver_s4.blog_drafts SET cms_publish_status='published', cms_post_id=$2, published_at=NOW() WHERE draft_id=$1::uuid",
                draft_id, str(result.post_id),
            )
            logger.info("cms_publish_ok draft=%s wp_post=%s", draft_id, result.post_id)
            return True

        except Exception as exc:
            await conn.execute(
                "UPDATE acp_shared.acp_cms_publish_queue SET status='failed', retries=retries+1, last_error=$2 WHERE queue_id=$1",
                queue_id, str(exc)[:500],
            )
            await conn.execute(
                "UPDATE acp_silver_s4.blog_drafts SET cms_publish_status='failed' WHERE draft_id=$1::uuid",
                draft_id,
            )
            logger.error("cms_publish_fail draft=%s error=%s", draft_id, exc)
            return False
