"""Social-post publish adapter interface — AA-462, T11's first non-blog channel.

Deliberately a NEW small package, not services/acp_s4_blog/cms/ (that one's dataclass shape is
CMS-post-specific: title/slug/seo_title/seo_meta, a WordPress-shaped concept a social feed post
has none of) and not services/acp_s4_social/ (that name is tied to dead ACPv1 — see CLAUDE.md's
own KNOWN TECH DEBT notes; reusing it here would blur the "ACPv1 is dead" boundary ADR-2026-038
§0.5 already established for every other T-series build in this repo — write fresh, don't reuse
legacy code/names).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class SocialPost:
    message: str
    link: Optional[str] = None


@dataclass
class SocialPostResult:
    post_id: str
    post_url: str
    platform: str


class SocialAdapter(ABC):
    @abstractmethod
    async def create_post(self, post: SocialPost) -> SocialPostResult: ...
