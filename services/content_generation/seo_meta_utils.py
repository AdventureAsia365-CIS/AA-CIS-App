"""AA-205: shared seo_meta band + sentence helpers (single source of truth).

Imported by graph.py (validate_node) AND flag_fix_node.py (post-repair band guard).
Extracted in AA-205: graph.py imports flag_fix_node, so flag_fix CANNOT import graph.py
back (circular) — this neutral module breaks the cycle and kills BAD_META_ENDINGS drift.
"""
import re

SEO_META_MIN = 140
SEO_META_MAX = 155

# AA-201: seo_meta must be a complete sentence (port of v5 repair_seo_fields)
BAD_META_ENDINGS = {
    "and", "with", "including", "or", "plus", "to", "for", "from", "in", "on", "at",
}


def meta_complete_sentence(meta: str) -> bool:
    """True when seo_meta reads as a complete sentence (period end, >=8 words,
    no trailing preposition/conjunction). No verb-whitelist (AA-201 revision)."""
    t = (meta or "").strip()
    if not t.endswith("."):
        return False
    words = t.split()
    if len(words) < 8:
        return False
    last = re.sub(r"[^a-zA-Z]", "", words[-1].lower()) if words else ""
    if last in BAD_META_ENDINGS:
        return False
    return True


def meta_in_band(meta: str) -> bool:
    """In [SEO_META_MIN, SEO_META_MAX] AND a complete sentence."""
    t = (meta or "").strip()
    return SEO_META_MIN <= len(t) <= SEO_META_MAX and meta_complete_sentence(t)


def _trim_to_sentence(text: str, limit: int) -> str:
    """Trim to <= limit, preferring last sentence terminator within limit.
    Trims DOWN only — never pads up. Local mirror of admin_pipeline trim (no cross-import)."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    window = t[:limit]
    cut = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
    if cut != -1:
        return window[:cut + 1].rstrip()
    space = window.rfind(" ")
    if space != -1:
        return window[:space].rstrip()
    return window.rstrip()


def best_meta_candidate(post_repair: str, pre_repair: str) -> str:
    """AA-205 deterministic post-repair band guard (no LLM, no padding, no escalate).
    Preference: (1) post if in band; (2) pre trimmed sentence-aware to <=MAX if that lands
    in band; (3) post unchanged (no salvage — caller may re-repair; AA-215 revalidate has
    already flagged it correctly)."""
    post = (post_repair or "").strip()
    pre = (pre_repair or "").strip()
    if meta_in_band(post):
        return post
    if pre:
        trimmed = _trim_to_sentence(pre, SEO_META_MAX)
        if meta_in_band(trimmed):
            return trimmed
    return post
