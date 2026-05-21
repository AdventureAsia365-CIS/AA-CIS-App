"""CMS Adapter interface — PRD v1.0 §4.1"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BlogContent:
    title: str
    content_html: str
    slug: str
    seo_title: str
    seo_meta: str
    status: str = "draft"  # Always 'draft' per PRD v1.0 Q10 — human publishes manually


@dataclass
class CMSPostResult:
    post_id: int
    post_url: str
    status: str
    cms_type: str


class CMSAdapter(ABC):
    @abstractmethod
    async def create_post(self, content: BlogContent) -> CMSPostResult: ...
