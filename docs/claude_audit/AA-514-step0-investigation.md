# AA-514 STEP0 — investigation record (2026-09-02)

## §1. Current F1-F9 gates — Linear's claim confirmed accurate

Read `services/acp_content_writing/quality_gates.py` in full: F1_grounding, F2_banned_patterns,
F3_structural_variance (blog-only), F4_extreme_length, F5_atom_density (blog-only),
F6_cta_present, F7_faq_dedup (blog-only), F8_framework, F9_brand_voice. Matches Linear's own
"F1≈grounding, F2≈banned patterns, F3≈structural variance blog-only, F5≈atom density, F7≈FAQ
dedup" exactly — confirmed, not assumed.

## §2. Origin's 11 gates (`src/aa_social/gates/__init__.py`) — GATES tuple read verbatim

grounding, claim support, citation density, **promises an option**, banned patterns (fixable),
structural variance (Blog), heading hierarchy (Blog), word count (Blog), FAQ presence (Blog),
FAQ adds something (Blog), **SEO surface** (Blog, fixable). Confirms the 2 real gaps Linear names.
Also confirms: only 2 of 11 gates are `fixable=True` — banned patterns and SEO surface. Everything
else (including `promises an option`) is NOT fixable — ships flagged, with a note for a human,
never auto-repaired. `promises an option` has `channels=None` (applies to EVERY channel in the
origin, not just Blog).

## §3. `docs/adr/0023-a-gate-flags-rather-than-blocks.md` + `ROUNDS = 3` — corrected premise

Read verbatim: ADR 0023 is the flag-not-block pattern (`gates/__init__.py`'s own module
docstring: *"repair() gives the writer up to three passes at the violations a writer can
honestly fix — the search surface and the banned phrases — and then the Piece ships carrying
whatever is left as a flag with a note"*). `ROUNDS = 3` is a real constant, but it bounds the
origin's OWN repair loop, which retries ONLY the 2 fixable gates up to 3 times specifically.

**Corrected premise (STEP0 finding, not a stop-worthy contradiction):** AA-CIS's T9/T10 does NOT
have — and was never asked to build — a per-gate-type "3 rounds" mechanism. `MAX_ATTEMPTS = 2`
(service.py) is a flat, uniform cap already applied to ANY `repairable=True` gate failure
(confirmed by reading `run_write_background()` — this was AA-450's own deliberate simplification,
"ONE endpoint, write→check→up to 1 retry", already documented in this repo's CLAUDE.md). Reading
`gate_banned_patterns()` (F2) confirms it is ALREADY `repairable=True` today and already
participates in exactly this same uniform 2-attempt loop — NOT a distinct 3-count mechanism.
"đưa vào nhóm fixable (auto-fix tối đa 3 lần, giống banned patterns hiện nay hoạt động thế nào)"
is read as: give the new SEO-surface violations the SAME `repairable=True` treatment F2 already
has (participates in the existing uniform loop) — not as an instruction to build a NEW,
inconsistent 3-count mechanism for one gate only. No architecture decision needed here.

## §4. `gates/shape.py::seo_surface()` + real schema gap — asked, decided by Nghiệp

Read verbatim: checks `piece.seo_title` (≤60 chars, contains keyword), `piece.meta_description`
(120-158 chars, ends in terminal punctuation, contains keyword), `piece.slug` (lowercase-kebab,
≤60 chars). **Confirmed real gap**: `acp_shared.content_piece` (migration 115) has ONLY
`content_text` — no seo_title/meta_description/slug/keyword field at all, and T9's writer output
contract has always been plain text, never structured. This is a genuine architecture fork (new
migration + new writer-output shape for blog specifically), not a simple gate-function addition —
asked directly via AskUserQuestion. **Nghiệp's decision: full port** — migration 136 adds the 3
columns; blog-channel T9 output becomes a JSON envelope `{seo_title, meta_description, slug,
body}` instead of plain text (non-blog channels' output contract is UNCHANGED, still plain text).
`keyword` (needed for the "contains keyword" checks) is sourced from the SAME
`angle_gate_request.dfs_paa_snapshot.related_keywords[0]` T8 already snapshots (AA-501, migration
127) — no new DFS call, no new fetch.

## §5. `promises_an_option` — real data-shape gap, resolved without escalation

`truth.promises_an_option()` needs to know which cited Atom is "offered" (optional) vs "included"
— the origin precomputes this into a separate `offered_moments` table (scanned from itinerary
text against `offered-phrases.toml`'s `at_a_price`/`offered` word lists at atomization time).
AA-CIS has no such table or column anywhere (confirmed by grep — 0 real hits). **Resolved without
escalation** (unlike §4, this doesn't require a new migration/table): scan the SAME atom text
T9 already holds in memory (`atom_text`, or per-Segment text for a Route pick) for the SAME
ported phrase list, inline, at gate-check time — no new persisted classification needed, since
T9/T10 only ever needs this classification for the ONE piece currently being checked, not stored
long-term. Ported the exact `at_a_price`/`offered`/`hedges` word lists from `offered-phrases.toml`
verbatim (not re-authored). `promises_an_option` applies to EVERY channel (origin's own
`channels=None`) — for a non-Route/non-blog piece (no citation tags at all, since AA-CIS's tag
mechanism is blog-only), the check runs against the WHOLE content_text vs. the single atom_text
(no per-sentence tag mapping needed or possible); for a Route pick with real per-sentence
`[R:atom_id]` tags (AA-513), it maps each cited sentence to its OWN Segment's text.

## §6. F3 route-aware — confirmed buildable with existing AA-513 data, no new gap

`gate_structural_variance()`'s current H2-section-length check is generic (any H2s). AA-513
already tags each sentence with its OWN Segment's atom_id when the piece has ≥2 Segments — reused
directly here: when `route_segments` (>1) is given, map each H2 SECTION to the Segment whose id
is cited most inside it, and check variance BETWEEN those Segment-mapped section lengths
specifically (not between arbitrary H2s that might not correlate to a Segment at all). Falls back
to the existing generic H2 check when `route_segments` is None/single — byte-identical to today.

## Net STEP0 conclusion — real remaining build scope for AA-514

1. Migration 136: `content_piece.seo_title`/`meta_description`/`slug`.
2. `prompts.py`: blog-channel writer output becomes a JSON envelope (body + 3 SEO fields);
   non-blog unchanged. New `keyword` param (from dfs_paa_snapshot).
3. `generate.py`: `write_content()`/`rewrite_with_feedback()` return `(content_text, cost,
   seo_meta_dict)` — `seo_meta_dict` is `{}` for non-blog (parses JSON for blog, plain text
   passthrough for everything else).
4. `service.py`: `start_write()` resolves `keyword`; `run_write_background()`/`_finalize_piece()`
   thread the 3 new fields through to persistence.
5. `quality_gates.py`: new `gate_seo_surface()` (fixable/repairable=True, blog-only, exact
   thresholds ported verbatim from `gate-thresholds.toml`: seo_title_max_chars=60,
   meta_description_min/max_chars=120/158, slug_max_chars=60); new `gate_promises_an_option()`
   (never fixable, every channel); `gate_structural_variance()` gains optional `route_segments`
   for route-aware variance; `run_quality_gates()` wires all three in.
