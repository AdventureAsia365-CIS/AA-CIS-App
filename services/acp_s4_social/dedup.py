"""Cross-platform deduplication for S4.2 Social Media Content Engine.

ADR-2026-010: Jaccard threshold = 0.32 for cross-platform similarity detection.
"""
import re

JACCARD_THRESHOLD = 0.32  # ADR-2026-010


def tokenize(text: str) -> set:
    return set(re.findall(r'\b\w+\b', text.lower()))


def jaccard_similarity(text_a: str, text_b: str) -> float:
    a, b = tokenize(text_a), tokenize(text_b)
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def check_cross_platform_dedup(tiktok: str, fb_post: str, fb_ad: str) -> list[str]:
    flags = []
    if jaccard_similarity(tiktok, fb_post) >= JACCARD_THRESHOLD:
        flags.append("tiktok_fb_post_too_similar")
    if jaccard_similarity(tiktok, fb_ad) >= JACCARD_THRESHOLD:
        flags.append("tiktok_fb_ad_too_similar")
    if jaccard_similarity(fb_post, fb_ad) >= JACCARD_THRESHOLD:
        flags.append("fb_post_fb_ad_too_similar")
    return flags
