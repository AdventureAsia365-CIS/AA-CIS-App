"""
services.acp_shared.competitor_index — AA-445-02, B4 (CompetitorIndex) +
score_distinctiveness().

Ports `aamc/corpus.py`'s `competitor_index()`/`score_distinctiveness()` (aa-marketing-v2
research build, cited in full in Linear AA-317's comment) onto this repo's real architecture:
- Domain source is `acp_silver_s2.competitor_inputs` (AA-88, already built — see AA-445-01
  STEP0 Q3/Q4) instead of a fresh `domains: list[str]` input. Grain is (tenant_id, country),
  matching that table.
- Fetched phrase corpus is cached in `acp_shared.competitor_index_cache` (migration 111) — the
  reference implementation persisted to a JSON `Workspace` file; this repo has no such
  file-store concept, everything here is Postgres-backed. TTL 24h.
- Fetch uses `httpx.AsyncClient` (already a pinned dependency, used the same
  best-effort/no-`requests`-package way in `services/acp/s2/tools/apify.py`) instead of the
  literal `requests` package (not in requirements.txt) — same "one plain best-effort GET per
  domain" semantics, just async-native instead of blocking the event loop.

Only wired at T5 (`services/acp_produce/tenant_pipeline.py::run_t5_atomize`,
`owner_scope=tenant_id` atoms) — NOT at N2's platform-scope decompose
(`api/routers/v1_atoms.py::_decompose_inline`, `owner_scope='platform'`). See
`docs/implementation-notes/AA-445-02-distinctiveness-dfs-t2-build.md` Decision 1 for why: a
CompetitorIndex is inherently tenant-relative, and platform-scope atoms have no single owning
tenant to score against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import structlog

logger = structlog.get_logger()

_FETCH_TIMEOUT_S = 15.0  # per-domain, matches aamc/corpus.py's own timeout=15
_USER_AGENT = "aa-cis-competitor-index/1.0"
_MAX_PHRASES_PER_DOMAIN = 120  # aamc/corpus.py's own cap
_PHRASE_MIN_LEN = 40           # aamc/corpus.py: 40 < len(s) < 220
_PHRASE_MAX_LEN = 220
_CACHE_TTL_HOURS = 24  # AA-445-02 Decision 2 — see implementation notes

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SENT_SPLIT_RE = re.compile(r"[.!?]")
_TOKEN_RE = re.compile(r"[a-z]{4,}")  # aamc/corpus.py: 4+ char lowercase words only


@dataclass
class CompetitorIndex:
    """Same shape/semantics as aamc/models.py's CompetitorIndex, minus the
    Workspace-persistence fields this repo doesn't have."""
    phrases: list[str] = field(default_factory=list)
    competitors: dict[str, list[str]] = field(default_factory=dict)  # domain -> its own phrases


def score_distinctiveness(text: str, idx: CompetitorIndex) -> str:
    """DET: does any competitor mention this? Token-overlap against the competitor phrase
    corpus. Verbatim port of aamc/corpus.py::score_distinctiveness() — same thresholds, same
    MED-when-empty fallback (AA-317: this is a deliberate honest-middle default, not a bug)."""
    if not idx.phrases:
        return "MED"  # no index yet (or fetch failed for every domain) — honest middle
    tokens = {w for w in _TOKEN_RE.findall(text.lower())}
    if not tokens:
        return "LOW"
    best = 0.0
    for phrase in idx.phrases:
        ptok = {w for w in _TOKEN_RE.findall(phrase.lower())}
        if not ptok:
            continue
        overlap = len(tokens & ptok) / len(tokens)
        best = max(best, overlap)
    if best >= 0.6:
        return "LOW"    # competitors already say the same thing — not distinctive
    if best >= 0.3:
        return "MED"
    return "HIGH"        # little/no overlap — genuinely distinctive detail


def _extract_phrases(html_or_text: str) -> list[str]:
    """Strip tags, collapse whitespace, split on sentence punctuation, keep the
    40-220 char sentences (aamc/corpus.py's own bounds — filters both nav/menu
    fragments and run-on paragraphs), cap at 120/domain."""
    text = _TAG_RE.sub(" ", html_or_text or "")
    text = _WS_RE.sub(" ", text).strip()
    sents = [s.strip() for s in _SENT_SPLIT_RE.split(text) if _PHRASE_MIN_LEN < len(s.strip()) < _PHRASE_MAX_LEN]
    return sents[:_MAX_PHRASES_PER_DOMAIN]


async def _fetch_domain(client: httpx.AsyncClient, domain: str) -> list[str]:
    """Best-effort homepage fetch — any failure (timeout, DNS, non-200, TLS) just
    yields zero phrases for that domain, never raises. Mirrors aamc/corpus.py's own
    try/except RequestException -> pages[d] = "" fallback."""
    url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    try:
        resp = await client.get(url, timeout=_FETCH_TIMEOUT_S, headers={"User-Agent": _USER_AGENT})
        if resp.status_code != 200:
            return []
        return _extract_phrases(resp.text)
    except Exception as exc:
        logger.warning("competitor_fetch_failed", domain=domain, error=str(exc))
        return []


async def _load_cache(pool, tenant_id: str, country: str) -> CompetitorIndex | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT phrases, competitors
            FROM acp_shared.competitor_index_cache
            WHERE tenant_id = $1::uuid AND country = $2
              AND fetched_at > NOW() - make_interval(hours => $3)
        """, tenant_id, country, _CACHE_TTL_HOURS)
    if not row:
        return None
    import json
    phrases = json.loads(row["phrases"]) if isinstance(row["phrases"], str) else row["phrases"]
    competitors = json.loads(row["competitors"]) if isinstance(row["competitors"], str) else row["competitors"]
    return CompetitorIndex(phrases=list(phrases or []), competitors=dict(competitors or {}))


async def _save_cache(pool, tenant_id: str, country: str, idx: CompetitorIndex) -> None:
    import json
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO acp_shared.competitor_index_cache
                (tenant_id, country, phrases, competitors, fetched_at)
            VALUES ($1::uuid, $2, $3::jsonb, $4::jsonb, $5)
            ON CONFLICT (tenant_id, country) DO UPDATE SET
                phrases = EXCLUDED.phrases, competitors = EXCLUDED.competitors,
                fetched_at = EXCLUDED.fetched_at
        """, tenant_id, country, json.dumps(idx.phrases), json.dumps(idx.competitors),
            datetime.now(timezone.utc))


async def build_competitor_index(tenant_id: str, country: str, pool) -> CompetitorIndex:
    """B4 — fetch/refresh a tenant's CompetitorIndex for one country.

    Reads active domains from acp_silver_s2.competitor_inputs (AA-88). Cache-first
    (24h TTL, acp_shared.competitor_index_cache); on a cache miss, fetches every
    active domain's homepage best-effort and persists the result. Returns an EMPTY
    index (idx.phrases == []) if the tenant has declared zero competitor URLs for
    this country, or if every fetch failed — score_distinctiveness() already
    handles that case correctly (returns MED), so callers don't need a separate
    empty-index branch.
    """
    cached = await _load_cache(pool, tenant_id, country)
    if cached is not None:
        return cached

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT url FROM acp_silver_s2.competitor_inputs
            WHERE tenant_id = $1::uuid AND country = $2 AND is_active = TRUE
        """, tenant_id, country)
    domains = [r["url"] for r in rows]

    idx = CompetitorIndex()
    if not domains:
        logger.info("competitor_index_no_domains", tenant_id=tenant_id, country=country)
        # Still cache the empty result — avoids re-querying competitor_inputs (a cheap
        # query, but consistent behavior) on every T5 call for a tenant with none declared.
        await _save_cache(pool, tenant_id, country, idx)
        return idx

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for domain in domains:
            phrases = await _fetch_domain(client, domain)
            idx.competitors[domain] = phrases
            idx.phrases.extend(phrases)

    logger.info("competitor_index_built", tenant_id=tenant_id, country=country,
                domain_count=len(domains), phrase_count=len(idx.phrases))
    await _save_cache(pool, tenant_id, country, idx)
    return idx
