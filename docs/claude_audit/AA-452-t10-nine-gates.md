# AA-452 — T10: extending F1/F2/F6/F8/F9-adjusted to the full F1-F9 gate set

## STEP0 finding #1 — the task's own premise was off by one gate

AA-452 was scoped assuming AA-450 shipped 5 T10 gates (F1/F2/F6/F8/F9-adjusted) with 4 missing
(F3/F4/F5/F7). Re-reading `services/acp_content_writing/quality_gates.py` against
`services/acp_produce/gates.py` (the real N7 source, gate names/mechanisms confirmed by reading
the code, not guessed from sequence order) found **6 gates already shipped**, not 5:
`F6_cta_present`, `F1_grounding`, `F2_banned_patterns`, **`F4_extreme_length`**, `F8_framework`,
`F9_brand_voice`. `F4_extreme_length` already exists — it's the exact "extreme length only, no
word-count band" gate `docs/claude_audit/AA-450-02-t10-gate-map.md`'s own F4 row proposed
("removed, replaced by a light sanity check"); that doc's *summary line* just undercounted it as
"5 gates" (a stale line in that doc's own prose, not in the code). The real gap was **3 missing
gates (F3, F5, F7), not 4.**

## STEP0 finding #2 — F3/F7's "not applicable to T9" reasoning didn't hold for the `blog` channel

AA-450-02's gate map dismissed F3 (structural variance) and F7 (FAQ dedup) as "T9 never produces
N7-style long-form blog/FAQ output." `services/acp_angle_gate/channel_style.py`'s own `blog`
entry (added AA-449) states otherwise: `"structure": "Hook→context/why this destination→
structured H2 sections→FAQ (if TOFU)→CTA"` — the same H2+FAQ shape N7's gates target. `prompts.py`
fed this text to the writer as loose guidance but never asked for literal markdown markup, so
whether real output would have parseable H2/FAQ structure was genuinely unknown before this task.

## Decision (confirmed with Nghiep, 24/08/2026) — Option 3

Rather than porting F3/F5/F7 against content whose real shape was unverified, or leaving them out
on the same "no target" reasoning already shown to be shaky for `blog`: **make the `blog`
channel's writer prompt actually produce the markup these gates need FIRST** (real markdown `## `
H2 headers, a `## FAQ` section with `**Q: .../A: ...` pairs when the piece has one, and
`[R:{atom_id}]` citation tags after fact-bearing sentences — see `prompts.py`'s
`_BLOG_FORMAT_INSTRUCTIONS`), THEN port the 3 gates, scoped to `channel == 'blog'` only. The other
7 channels are completely unaffected — same 6-gate stack as before, byte-identical prompts.

## Gate-by-gate (the 3 new ones)

| N7 gate | T9/T10 treatment |
|---|---|
| F5 atom density | **Added, blog-only.** Needs `[R:atom_id]`/`[F:id]` tags — T9 has exactly one atom per piece, so (unlike N7) there's no closed-world/multi-id check to make, only "does this 300-word window have >=1 citation at all." Ported window-chunking logic verbatim from `gates.py::gate_atom_density()` (`ATOM_DENSITY_WORDS=300`, skip a trailing chunk under `window//2`). |
| F3 structural variance | **Added, blog-only.** Same 3 checks as N7 (one-sentence-paragraph exists / longest H2 section >=1.4x second-longest when >=3 sections / at most 1 bulleted list), ported verbatim, now meaningful because `prompts.py` actually asks the blog writer for real `## ` H2 markup. |
| F7 FAQ dedup | **Added, blog-only.** No-op (`passed=True`) when the piece has no `## FAQ` section — `prompts.py`'s instruction only asks for one "if the piece includes a FAQ section" (mirrors N7's own "if TOFU" conditionality), most blog pieces won't have one. Same intra-piece-only scope N7's own gate has (cross-time dedup against previously-published FAQs needs a table that doesn't exist for T9 either — same real gap, not a new one). |

F4 (`gate_extreme_length`) is unchanged in behavior but now measures the citation-tag-STRIPPED
text, not raw `content_text` — a citation tag is internal markup and shouldn't count toward a
length ceiling meant to bound what the tenant actually reads. This only matters for `blog` (the
only channel that ever has tags); the other 7 channels see identical before/after behavior since
`strip_citation_tags()` on untagged text is a no-op.

## The tag+strip mechanism — the highest-risk part of this task

Emitting `[R:atom_id]` tags into T9's output reopens the exact risk AA-450 avoided by NOT using
tags in the first place (`quality_gates.py`'s own `gate_grounding()` docstring: "a visible
citation tag would look broken" in tenant-facing copy). Investigated whether N7 itself already
solves "strip tags before the reader sees them" (T11 publish, or `acp_deliver`'s packet assembly)
and confirmed it does **not** — `packets.py::assemble_packet()` carries `body_tagged` through
unchanged, and grepping `services/acp_produce/` + `acp_deliver` for a strip step found none. N7
gets away with this only because T11 (publish) isn't built yet; T9 has no such luxury — its write
endpoint's response IS the tenant-facing artifact, today, with no downstream step to fix it later.

**Design**: content stays tagged for the ENTIRE write→check pipeline (T9's write call for
`channel=='blog'`, all of T10's gates) — `strip_citation_tags()`/`deep_strip_citation_tags()`
(`quality_gates.py`) run exactly once, in `service.write_and_check()`, after the attempt loop
concludes and before `_persist_piece()` — on `content_text`, on every violation string inside
`gate_ledger`/`repair_log` (a gate's own violation message can quote a tagged excerpt — see
`gate_grounding()`'s comment), and on `held_reason`. This runs for BOTH `status='approved'` and
`status='held'` outcomes — a held piece is fully visible to the tenant (content + reason + full
ledger, same `_hold()` "hold VISIBLE, never silent" precedent N7 already documents), so it needs
the exact same scrub an approved piece gets, not a lesser one. Runs unconditionally for every
channel — a no-op for the 7 that never produce a tag, a real scrub for `blog`.

**No new DB column for the tagged intermediate.** Considered adding a nullable
`content_text_tagged` debug column to `acp_shared.content_piece` and decided against it: T10 has
no admin review-queue UI (still out of scope, same as AA-450), so there is no real consumer for a
persisted tagged copy today — adding one would be speculative schema surface for a debugging need
that doesn't exist yet (same "extend from real failures, don't guess ahead of data" discipline
ADR-2026-009 already applies elsewhere in this codebase). The tagged text lives only as a local
variable inside `write_and_check()` for the duration of one request and is discarded once the
final scrub runs. If a real debugging need for the tagged intermediate shows up later, add the
column then, against real evidence of needing it.

**Test coverage** (`tests/unit/test_aa452_t10_nine_gates.py`,
`TestWriteAndCheckStripsTagsBeforeOutput`): asserts against the ACTUAL positional args
`_persist_piece()` sends to the INSERT (a fake `RETURNING` that echoes those args back, not a
hand-typed static mock row — the first version of these tests asserted only against a hardcoded
mock return value and would have passed even if the strip step were silently deleted; fixed
before this PR). Covers an approved blog piece, a held blog piece (both content + `held_reason` +
`gate_ledger`), and confirms non-blog channels are unaffected (no tag ever produced, strip is a
verified no-op).
