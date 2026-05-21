"""
WordPress REST API v2 adapter — PRD v1.0 Q7.
Auth: Application Password (WP 5.6+, base64 Basic auth).
Posts always created as 'draft' — human publishes manually (PRD v1.0 Q6, Q10).
"""
import base64
import logging
from typing import Optional

import aiohttp

from .base import CMSAdapter, BlogContent, CMSPostResult

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)


class WordPressAdapter(CMSAdapter):
    def __init__(self, wp_url: str, username: str, app_password: str):
        self.api_base = wp_url.rstrip("/") + "/wp-json/wp/v2"
        credentials = base64.b64encode(f"{username}:{app_password}".encode()).decode()
        self._auth_header = f"Basic {credentials}"

    def _headers(self, content_type: str = "application/json") -> dict:
        return {"Authorization": self._auth_header, "Content-Type": content_type}

    async def create_post(self, content: BlogContent) -> CMSPostResult:
        payload = {
            "title": content.seo_title or content.title,
            "content": content.content_html,
            "slug": content.slug,
            "status": "draft",
            "meta": {
                "_yoast_wpseo_title": content.seo_title,
                "_yoast_wpseo_metadesc": content.seo_meta,
            },
        }

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(
                f"{self.api_base}/posts",
                json=payload,
                headers=self._headers(),
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    raise RuntimeError(f"WP API {resp.status}: {body[:300]}")
                data = await resp.json()

        return CMSPostResult(
            post_id=data["id"],
            post_url=data["link"],
            status=data["status"],
            cms_type="wordpress",
        )
