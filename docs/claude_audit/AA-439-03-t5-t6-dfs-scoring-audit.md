# AA-439-03 — Original Design Doc Reading + Audit T5→T6 (Atomize → Atom Curation), DFS-Scoring Focus

Audit only, no code changed. Branch `feature/aa-439-tenant-tier-audit`. Part B (reading
`aa-marketing-v2`) was done first, in full, before touching any T5/T6 code, per the task's
explicit instruction.

**Headline: Nghiep's memory is half-right, in an important and correctable way.** The original
design genuinely does have automatic HIGH/MED/LOW atom scoring — but it's called
**distinctiveness**, computed by comparing an atom's text against a **scraped-competitor-content
index** (token overlap), not by DataForSEO relevance/volume scoring. DataForSEO does appear in
the original design, but for topic/brief research (keyword volume, SERP, PAA), never for scoring
individual atoms. **The current codebase already has the `distinctiveness` field, already has a
fully-built tenant-facing UI to display it (color-coded HIGH/MED/LOW badges, a summary
breakdown, a filter dropdown) — but the one function that would ever compute a real value for it
was never built. Every atom in the live database, 100% of them, sits at the column's default
value.** This is exactly the automation gap Nghiep suspected, just not literally "DFS" — and the
UI is sitting there ready for it.

---

## PART B — What `aa-marketing-v2` actually specifies

Read in full: `CONTEXT.md`, `README.md`, and `aamc/corpus.py` (the module implementing atom
decomposition + distinctiveness scoring), from
`docs/AI-gent-for automation works/aa-marketing-v2/`.

### B1. The HIGH/MED/LOW mechanism — quoted directly

`CONTEXT.md` §2.2 (Atom inventory):
> "An atom = one concrete, content-usable moment/detail from a trip's itinerary. Fields:
> atom_id, trip_id, text (verbatim-derived), activity_type, emotional_hook, visual_potential
> (1–3), persona_fit[], season_note, **distinctiveness (HIGH/MED/LOW — computed against the
> competitor index: does any competitor mention this?)**, media {...}, starred (bool,
> agency-set), usage_log[...], cooldown_until (default 6 weeks per channel), human_seam_notes[]."

`CONTEXT.md` §5, Module B: `B1 decompose_atoms(trip) -> atoms[]` · LLM — *"Post-step DET:
distinctiveness scoring vs competitor index (B4)."*

**The actual reference implementation** (`aamc/corpus.py:69-88`):
```python
def score_distinctiveness(text: str, idx: CompetitorIndex) -> str:
    """DET: does any competitor mention this? Token-overlap against the
    competitor phrase corpus."""
    if not idx.phrases:
        return "MED"  # no index yet — honest middle, refined when index lands
    tokens = {w for w in re.findall(r"[a-z]{4,}", text.lower())}
    if not tokens:
        return "LOW"
    best = 0.0
    for phrase in idx.phrases:
        ptok = {w for w in re.findall(r"[a-z]{4,}", phrase.lower())}
        overlap = len(tokens & ptok) / len(tokens)
        best = max(best, overlap)
    if best >= 0.6:
        return "LOW"    # competitors say the same thing
    if best >= 0.3:
        return "MED"
    return "HIGH"
```

**Input**: `CompetitorIndex.phrases` — built by `competitor_index()` (B4, `corpus.py:205-230`),
which fetches raw HTML from agency-declared competitor domains (from onboarding intake),
strips tags, splits into sentences 40-220 chars long, and keeps up to 120 phrases per domain.
**Algorithm**: plain word-token overlap (words ≥4 chars) between the atom's text and every
stored competitor phrase — the single best overlap ratio decides the bucket (≥0.6 → LOW,
≥0.3 → MED, else HIGH). **Output**: a purely deterministic (no LLM) string, one of `HIGH`/
`MED`/`LOW`, meaning "how distinctive is this detail versus what competitors already say" —
never seen a keyword-search-volume number at all.

### B2. Where DataForSEO actually appears in the original design — nowhere near atom scoring

`CONTEXT.md` §5, Module C (Research & Briefs): `C1 keyword_research` (DFS search_volume +
keyword_suggestions), `C2 serp_read` (DFS serp_organic + PAA), `C3 compile_brief` (uses C2's
SERP read for gap-analysis against ranking pages). All three feed **brief/topic construction**
— demand evidence, ranking-page gap analysis, FAQ sourcing. **None of the three ever touch an
atom's `distinctiveness` field or any per-atom score.** Grepped `corpus.py` (the file that
actually computes `distinctiveness`) for `dataforseo`/`DFS`/`DataForSEO` — zero hits.

**One genuine, if thin, connection exists, and it's worth stating precisely rather than
dismissing**: `CONTEXT.md`'s own prose description of B4 says its input is *"agency's declared
competitors (intake) + SERP-discovered rivals per destination (C2)"* — i.e., the design's own
prose imagines DataForSEO's SERP results being used to discover MORE competitor domains beyond
the agency-declared list, which would then feed the same competitor-index/distinctiveness
pipeline. **But the actual reference code (`competitor_index()`, quoted above) only implements
the agency-declared-domains half — it never calls into `C2`/DataForSEO at all.** So even in the
original reference build, the DFS-adjacent half of competitor discovery was spec'd in prose but
not implemented. **Conclusion: DataForSEO is not, and was never actually built to be, an atom
scoring input — the atom-scoring mechanism is competitor-content-overlap ("distinctiveness"),
full stop.** Nghiep's recollection of "DFS scores atoms" is most plausibly this same
prose line, reasonably read as "DFS is involved in getting atoms scored" — accurate in spirit
(there is automatic HIGH/MED/LOW atom scoring in the design), off on the specific mechanism.

---

## PART C — T5→T6 audit, verified against the code

### C1. `/portal/t6-atoms` — confirmed built, tenant-facing, and NOT admin-only (ADR §11.2 is stale)

`frontend/app/(tenant)/portal/t6-atoms/page.tsx` renders `<AtomsTab />`
(`_components/AtomsTab.tsx`, 190 lines, full read). The component's own header comment settles
this precisely:
> "AA-431 (T6 Atom Curation, tenant-facing)... Deliberately NOT a copy of
> `app/admin/curation/page.tsx` (826 lines, staff tool that browses every owner_scope across the
> whole platform) — this is tenant-scoped to the caller's own atoms only... a deliberately
> smaller tool for a tenant curating their own handful of tours, not AA staff curating hundreds."

**The ADR's §11.2 claim ("T6 FE: 100% admin-only, chưa build") is confirmed stale** — same
pattern as AA-439-01's T0/T1 findings: a real, deliberately tenant-scoped, tenant-facing build
(AA-431) shipped after whatever ADR text made that claim, and the claim was never updated.
Route slug (`t6-atoms`) was reserved by AA-430's route migration and this is confirmed to be its
first real use (`page.tsx`'s own comment).

### C2. Owner-scope isolation — confirmed no leak, re-verified with the actual endpoint code

`_resolve_atom_owner_scope()` (`admin_atoms.py:86-100`, same function AA-438-04 already found)
gates `GET /atoms`, `GET /atoms/summary`, `PATCH /atoms/bulk`, and `PATCH /atoms/{atom_id}` —
all four re-read in full this task, not assumed unchanged. Every one of them applies the
resolved `owner_scope` as a **WHERE clause on the actual UPDATE/SELECT**, not just a post-filter:
`PATCH /atoms/{atom_id}`'s own comment states it plainly — *"a tenant's UPDATE is WHERE-scoped,
so a guessed atom_id from outside their own scope 404s (not found) instead of being editable"* —
confirmed by reading the actual SQL (`admin_atoms.py:463-470`, `scope_clause` appended to the
`WHERE`). `AtomsTab.tsx`'s own comment independently confirms the frontend never sends
`owner_scope` as a param at all — it's derived server-side from the JWT, so there's no client
input a tenant could tamper with even in principle. **No leak found, no gap found.**

### C3. Curate actions — star / soft-delete / light text edit, backend supports more than the tenant FE exposes

Backend (`PATCH /atoms/{atom_id}`, full read) supports `starred`, `deleted` (soft-delete —
excluded from the N6 allocator's `_eligible_atoms()`, confirmed same code path
`allocator.py:107-118` already read in AA-440), and `text` (light edit, rejects empty string).
**`AtomsTab.tsx` (the tenant FE) only renders star/delete buttons — no text-edit input anywhere
in the component.** This is not a bug — the admin `/admin/curation` page is the one with the
richer edit surface (826 lines per its own referenced size) — but it means a real tenant cannot
correct a typo/wrong detail in an atom's text today, only star it, remove it, or leave it as-is.
Bulk actions (`PATCH /atoms/bulk`) exist server-side but `AtomsTab.tsx` has no multi-select UI
either — single-atom actions only, confirmed by the component's own comment ("no bulk multi-
select... a deliberately smaller tool").

### C4. Does T6 show ANY relevance signal today? Yes, fully built UI — fed by a scoring function that doesn't exist

**This is the central finding.** `AtomsTab.tsx`:
- Renders a `Badge` per atom with `atom.distinctiveness` (`HIGH`/`MED`/`LOW`), color-coded
  (`DIST_VARIANT`: HIGH→green "success", MED→amber "warning", LOW→gray "default",
  `:40-42,151`).
- Renders a summary stat row: Total atoms / Reviewed / **High distinctiveness** / **Medium** /
  **Low** (`:115-123`), sourced from `GET /atoms/summary`'s `distinctiveness_breakdown`.
- Has a filter dropdown: "All distinctiveness" / High / Medium / Low (`:126-132`), wired to the
  real `?distinctiveness=` query param `admin_atoms.py:190,248-249` accepts.

**All of this is fully wired, real code, not a stub.** But live-queried (22/08 17:32 UTC):

```sql
SELECT distinctiveness, COUNT(*) FROM acp_contract.tour_atoms
WHERE NOT deleted AND NOT is_empty_marker GROUP BY distinctiveness
```
```
LOW: 2566
```
**100% of every atom in the database — all 2566 non-deleted rows, both the 2551 platform-scope
ones and the 15 real tenant-scope ones — sit at `distinctiveness='LOW'`. Zero `HIGH`, zero
`MED`, anywhere, for any tenant, ever.** Confirmed why, in the current codebase's own inline
comment (`api/routers/v1_atoms.py:248-251`, already found by AA-438-04, re-verified here):
> "distinctiveness/media/usage_log/cooldown_until/human_seam_notes are deliberately absent from
> this INSERT — **`score_distinctiveness()` does not exist yet (AA-317, out of scope here)**, so
> those columns stay at their migration-079 defaults (`distinctiveness='LOW'`)."

**`score_distinctiveness` is the exact same function name as the reference implementation's**
(`aamc/corpus.py:69`) — confirming this isn't a different, unrelated feature; it's the same one
the original design specified, tracked under a real ticket number (AA-317), never built.
Grepped the whole current repo for `AA-317` — the one line above is the **only** mention
anywhere; no PR closed it, no other file references it.

**Not a deliberate removal** — checked for any ADR/removal rationale: ADR-2026-038 itself is
confirmed absent from this repo (per AA-438-01's earlier finding, not re-litigated here), so it
cannot be checked directly for a "cut this on purpose" note. Nothing in this codebase's own
comments, migrations, or commit history (grepped, one hit total) frames this as anything other
than a not-yet-built ticket. **Confirmed: this is a real, live gap between the original design
and the shipped code — not a considered-and-rejected feature.**

**Consequence for both T6 and the wider pipeline, confirmed by tracing every consumer of
`distinctiveness`:**
- **T6 itself**: the filter dropdown and summary breakdown are currently decorative — filtering
  to "High" or "Medium" always returns zero rows; every atom shows the same gray "LOW" badge.
  A tenant curating atoms today gets **zero automated prioritization signal** — exactly the
  unassisted-browsing experience Nghiep suspected, confirmed by data, not inference.
- **N5 Quarter Plan trip scoring** (`services/acp_planning/quarter.py:169`): `dist = sum({"HIGH":
  1.0,"MED":0.5,"LOW":0.1}[...]) / len(atoms)` — with every atom LOW, this term is **always
  exactly 0.1** for every trip that has any atoms at all, contributing a flat, non-differentiating
  0.03 (0.1 × the 0.3 weight) to every trip's score. The "distinctiveness" component of trip
  selection is currently inert.
- **N6 slot allocator's atom-selection weight** (`services/acp_planning/allocator.py:116`):
  `weight * (1.5 if starred else 1.0) * {"HIGH":1.5,"MED":1.0,"LOW":0.6}[distinctiveness]` — with
  every atom LOW and every atom's base `weight` also hardcoded to `1.0` at insert time (confirmed
  live: `weight_distribution` query returned a single bucket, `weight=1, count=2566` — every atom
  in the database), **the only signal that can currently differentiate one atom from another
  within a trip+channel slot is whether a human starred it.** Everything else about "which atom
  is better" is, today, a coin flip.

This was not previously stated this precisely in any prior AA-438/439/440 report — AA-438-04
found `score_distinctiveness()` doesn't exist and defaults to LOW, but did not trace the
downstream effect on Quarter Plan scoring or the N6 allocator weight formula the way this task
did, nor confirm the live 100%-LOW state with a fresh query.

### C5. "Unreviewed" filter — a real, if simpler, mitigation that already exists today

Separate from distinctiveness: `admin_atoms.py`'s `unreviewed_only` filter
(`ta.updated_at = ta.created_at` — an atom no PATCH has ever touched, `:207-213,252-253`) IS a
real, working, live-queryable signal a tenant can use today to focus on "atoms I haven't looked
at yet" — confirmed wired in `AtomsTab.tsx`'s checkbox (`:133-136`). It's not relevance
scoring, but it's a genuine, functioning way to avoid re-scanning the same atoms — worth noting
as a partial, already-shipped mitigation, distinct from (and not a substitute for) the missing
distinctiveness scoring.

### C6. How many atoms does a tenant actually face? One real data point

Live query: only **one** real tenant-scope tour has ever been atomized in this dev environment
— `test-agency`, tour `66ebe919-...`, **15 atoms**. No other real (non-platform) tour has any
tenant-scope atoms yet. This is the only concrete "atoms per tenant" sample available —
extrapolating, a tenant with even a modest handful of rewritten tours (say 10-20, well within
what a small agency might do in a normal month) would accumulate roughly 150-300 unscored,
unranked atoms using this one sample's rate, all rendered identically except for whichever ones
happen to be starred. This is a real, concrete number to weigh the DFS/distinctiveness-
automation ask against — not a hypothetical "someday" volume problem.

**Side observation, not deeply investigated (flagged, not chased)**: `starred` is `true` for
1993 of 2566 atoms (77%) live — a surprisingly high fraction for what's meant to be a deliberate
"guests rave about this" human action (all atoms insert with `starred=false`, per
`v1_atoms.py`'s insert code, so every `true` value was set by a later PATCH). Given nearly all
of this is platform-scope dev/test data, this is far more likely bulk-test-seeding than genuine
one-by-one curation — noted for whoever eventually reconciles/wipes this test data (per the
AA-438 summary's Data Cleanup Plan), not investigated further here.

### C7. T6→T7 handoff — no trigger button exists, consistent with T7 not being built yet

Grepped `AtomsTab.tsx` for any "done curating, proceed to planning" action — none found. This is
consistent with AA-440's own finding that Quarter Plan/T7 tenant self-service hasn't been built
yet at all (still admin-only Gate B as of that audit) — there is currently nothing for T6 to hand
off to, so the absence of a button is expected, not a separate gap to flag.

---

## Summary

| Question | Answer |
|---|---|
| Does the original design have HIGH/MED/LOW atom scoring? | **Yes** — "distinctiveness," computed via competitor-content token-overlap (`score_distinctiveness()`, `aamc/corpus.py`) |
| Is it DataForSEO-based? | **No** — DFS is used elsewhere (topic/brief research), never touches atom scoring in the reference implementation |
| Does the current codebase have the field? | **Yes** — `acp_contract.tour_atoms.distinctiveness`, same field name, same HIGH/MED/LOW values |
| Does the current codebase have the scoring function? | **No** — `score_distinctiveness()` confirmed not implemented (`AA-317`, tracked, not removed) |
| Does the current UI support showing it? | **Yes, fully** — badge, summary breakdown, filter — all real, all currently showing 100% LOW/nothing |
| Live data confirmation | 100% of 2566 real atoms are `distinctiveness='LOW'`, weight=1.0 flat — only `starred` differentiates anything today |
| Downstream effect | Quarter Plan's distinctiveness scoring term and N6's allocator distinctiveness multiplier are both currently inert |
| `/portal/t6-atoms` real/admin-only? | **Real, tenant-facing** — ADR §11.2's "100% admin-only" claim is stale |
| Owner-scope leak? | None found — WHERE-scoped on every write, confirmed by code |
| T6→T7 button? | None — expected, since T7 self-service doesn't exist yet (AA-440) |

## Open items — explicitly unconfirmed / out of scope

- Whether/how to build `score_distinctiveness()` for the current codebase (competitor-scrape
  based, like the reference; or a different mechanism, e.g. genuinely DataForSEO-driven as
  Nghiep originally recalled) — not designed here, flagged as the concrete next decision.
- The `starred=true` on 77% of atoms — flagged, not investigated (likely test-seed artifact).
- Whether `acp_contract.tour_atoms.weight` (currently always 1.0) is meant to ever vary, and by
  what mechanism (usage-based learning per the original design's H4 `adjust`, §1.8) — out of
  scope for this task, noted as a related gap in the same "no per-atom differentiation" family.
