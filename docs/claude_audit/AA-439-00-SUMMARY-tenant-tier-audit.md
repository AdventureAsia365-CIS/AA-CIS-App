# AA-439 — Tenant Tier Audit: Full Summary (Tasks 01→08)

Consolidates `AA-439-01` through `AA-439-08` — the complete tenant-tier (T0-T11) audit of
AA-CIS-App, run 22-23/08/2026 on branch `feature/aa-439-tenant-tier-audit` (which also carries
AA-438's and AA-440's commits, merged earlier in this same audit cycle). No code changed across
any of the 8 tasks, except one deliberate live test in AA-438-03 (a different branch's task,
not this one) — every AA-439 task was read-only plus live queries and one hash-verification.

Format follows `AA-438-00-SUMMARY-admin-tier-audit.md`. Read the 8 underlying reports for the
full evidence trail (`path:line` + real query/response) behind every line below.

---

## What the tenant pipeline actually is, confirmed end-to-end

```
T0 Brand Setup → T1 Tour Selection → [T2 Rewrite → T3 QA Gate → T5 Atomize, one job] → T4 My Catalog
                                                                                              ↓
T6 Atom Curation → (no handoff yet) → T7 Content Planning → (no handoff at all) → T8 Angle Gate
                                                                                        ↓
                                              T9 Final Write → T10 Quality Pass → T11 Publish
```

Two real breaks in this chain, both confirmed by code (not inferred): **T6→T7 has no button
because T7 isn't self-service yet** (AA-439-03/AA-440), and **T7→T8 has no connection in code at
all** — the two pipelines (N6 planning and the real angle-generation module) were built
independently and have never called each other (AA-439-06). T9→T10→T11 is one continuous,
working pipeline as far as T10; T11 stops cold (AA-439-08).

---

## All confirmed bugs/gaps found this audit (AA-439-01 → 08)

| # | Bug/gap | Where | Severity | Task |
|---|---|---|---|---|
| 1 | T0's brand-guide **upload** endpoint still hardcodes `tenant_id` to aa_internal AND, worse than its own code comment states, **401s outright for any real tenant** (routed through the admin-only proxy, which checks a cookie tenants never have) | `admin_pipeline.py:4196-4214`, `BrandTab.tsx:86` | Real, confirmed live | 01 |
| 2 | ADR's "T1 needs a brand-new endpoint" framing is stale — T1's real "Rewrite" button already runs the full T2→T3→T5 chain in one job (AA-425/436) | `v1_tours.py::trigger_rewrite()` | Not a bug — a doc/ADR staleness, corrected | 01 |
| 3 | T4 ("My Catalog") has **zero navigation to or from T6** — a tenant has no way to know a rewrite produces atoms unless they separately find "Atom Curation" in the sidebar | `CatalogTab.tsx` (full grep, no hits) | Real UX gap | 02 |
| 4 | `score_distinctiveness()` — the function that would give atoms real HIGH/MED/LOW scores — was **never built** (tracked as ticket AA-317, confirmed genuinely unbuilt, not a deliberate cut) | `v1_atoms.py:248-251` | Real, confirmed live: **100% of 2566 atoms are `distinctiveness='LOW'`, weight=1.0 flat** | 03 |
| 5 | Consequence of #4, traced further than any prior audit: Quarter Plan's trip-scoring formula and the N6 allocator's per-atom weight multiplier are **both currently completely inert** on the distinctiveness dimension — `starred` is the only thing that differentiates any atom from any other today | `services/acp_planning/{quarter,allocator}.py` | Real, confirmed | 03 |
| 6 | ADR's "T6 FE: 100% admin-only, chưa build" claim is stale — `/portal/t6-atoms` is real, tenant-scoped, and has been since AA-431 | `AtomsTab.tsx` | Doc staleness, corrected | 03 |
| 7 | No combined DFS+distinctiveness scoring formula exists anywhere in the original design (`aa-marketing-v2`) — confirmed by reading the whole folder; would be a genuinely new design decision | — | Not a bug — a research finding | 04 |
| 8 | Tenant rewrite (T1/T2) **never calls DataForSEO at all** — only the admin/A1 pipeline does; DFS data that exists per-tour is a side effect of A1, not of anything the tenant triggered | `v1_tours.py` (no DFS import), `admin_pipeline.py:474` | Real, confirmed | 05 |
| 9 | Persisted DFS data (`seo_context`) can be entirely null even when the row exists — confirmed with the newest real row, every numeric field null | `silver_aa_internal.seo_context` | Real caveat for future design | 05 |
| 10 | Real client sends 1 keyword per DataForSEO task, paying the full flat task price ($0.09) for what could cover up to 1,000 keywords at the same price — matters enormously if per-atom DFS scoring is ever built (~$467 vs ~$4-5 for the same 2,566 atoms, batched vs. not) | `dataforseo_client.py::fetch_keywords/fetch_keyword_ideas` | Real inefficiency, quantified | 05 |
| 11 | There is **no T7→T8 handoff in code at all** — not unwired, structurally disconnected; the N6 planning pipeline and the real angle-generation module have never called each other | full grep, `services/acp_produce/` has zero "angle" references | Real, confirmed | 06 |
| 12 | The real, complete, working angle-generation flow (`acp_s4_social/`) is 100% admin-gated and has **zero rows ever, in any environment** — confirmed at both the data level (06) and the code level: **no caller exists anywhere**, frontend or backend, for `/generate`/`/angles`/`/write` | `v1_s4_social.py`, full frontend grep | Real, confirmed | 06, 07 |
| 13 | `trust_ramp.py`'s automatic advancement logic (`suggest_ramp_transition`) has **zero callers anywhere** — dead code; only a manual staff-picked admin action can move a packet's ramp state, and that has **never happened once** (`audit_log` has 0 `publish_mode_transition` rows) | `trust_ramp.py`, `audit_log` | Real, confirmed live | 06 |
| 14 | **Corrected in 07**: the trust ramp IS chị Thư's original design (`aamc/delivery.py::publish_gates()`, a line-for-line match), not a separate AA-365 invention — resolves 06's open question | `aa-marketing-v2/aamc/delivery.py:157-174` | Not a bug — a research correction | 07 |
| 15 | Nghiep's 9-step angle workflow traces to a real 11-step source (`SKILL_v2.md`'s "Human-In-The-Loop Workflow") — not `aa-marketing-v2`; 7/11 steps match the current code cleanly | `stage4.2_..._v2/SKILL_v2.md:210-226` | Not a bug — a research finding | 07 |
| 16 | Brand/audience are validated, **required, caller-supplied** inputs in `ContentBrief` — nothing auto-applies a fixed value, contradicting the assumption that they're fixed; can't be fully checked in practice since nothing calls the module (see #12) | `acp_s4_social/brief.py:48-65` | Real discrepancy vs. assumption | 07 |
| 17 | The angle-output field format has a real, precise 3-way mismatch: source wants Name/Why it works/Best final style (3 fields); current code has 4 (`name`/`why_it_works`/`length_signal`/`style_signal`); **"formula fit" appears in neither the source nor the code** — it would be a new field, not a recovery | `angles.py:19-28` vs. `SKILL_v2.md:228-252` | Real, precise gap | 07 |
| 18 | `pipeline.py`'s own docstring ("C3/E1-E5 don't exist anywhere in this repo") is stale — E1/E2/E3 are real, Sonnet-backed, working code (`generation.py`, `adapt.py`) | `pipeline.py:6-13` | Doc staleness, corrected | 08 |
| 19 | `Channel Output Structures.xlsx` is **not used anywhere** in the real N7 pipeline — only 2 of its 7 channels are even covered (facebook, tiktok), with independently-written prompts that don't carry over the file's specific structure/avoid-list content | `adapt.py` vs. the xlsx (dumped in full, AA-439-07) | Real, confirmed | 08 |
| 20 | T10's F1-F9 gate stack is confirmed real and is the aa-marketing-v2 port — but it is a **separate implementation from T3's own QA check**, sharing only one small grounding-utility function, not the whole stack | `gates.py` vs. `tenant_pipeline.py` imports | Clarification, not a bug | 08 |
| 21 | T11 (Publish) confirmed cleanly absent — by the code's own docstring, not just by absence: `deliver_packet()`'s "delivered" is a DB-column flip only, no real social-platform API integration exists anywhere in the codebase | `packets.py:209-247`, full grep | Real, confirmed — matches ADR exactly | 08 |
| 22 | None of the 10 real "passed" pieces has ever advanced past packet `status='ready'` — zero `delivered_at` values anywhere; `acp_shared.usage_log` (the delivery-accounting table) **doesn't even exist** in this database | live query | Real, confirmed | 08 |

**Confirmed NOT bugs (investigated on suspicion, ruled out or clarified):** #2, #6, #7, #14, #15,
#18, #20 above are all doc-staleness corrections or research clarifications, not defects in the
running system.

---

## Full T0-T11 status, one line each

| Stage | Status | One-line reason |
|---|---|---|
| T0 Brand Identity Setup | **Live** (real gap) | AA-424 fix confirmed live; upload endpoint still 401s for real tenants (#1) |
| T1 Tour Selection / Browse Pool | **Live** | Hash-verified running code, triggers full T2→T3→T5 in one job (01) |
| T2 LLM Rewrite | **Live** | Same job as T1, `_rewrite_tour()` (01) |
| T3 Tenant QA Gate | **Live**, no dedicated UI | Escalate-but-continue (AA-436); separate implementation from T10 (08) |
| T4 Tenant Tour Pool / My Catalog | **Live**, partial visibility | Only T3's auto-pass badge shows; no T5/T6 result; no nav to T6 (#3) |
| T5 Atomize | **Live**, unscored | Always runs (AA-436); distinctiveness scoring never built (#4) |
| T6 Atom Curation | **Live**, real but unassisted | Real & tenant-scoped (ADR's "admin-only" claim stale, #6); nothing to show for relevance |
| T7 Content Planning / Quarter Plan | **Partial** | Business logic real & tenant-scoped; still admin-Gate-B-gated in practice (AA-440) |
| T8 Angle Gate | **Missing** (as tenant self-service) | Real, complete code exists but 100% admin-gated, zero callers anywhere (#11, #12) |
| T9 Final Write | **Live** | E1/E2/E3 real, Sonnet-backed (08) |
| T10 Quality/Editor Pass | **Live** | F1-F9 real, aa-marketing-v2-ported, actively holding real pieces (08, #20) |
| T11 Publish | **Missing** | Confirmed by the code's own docstring — DB marker only, no social-platform integration (#21, #22) |

**Net: 8 of 12 stages fully live, 1 partial (T7), 2 missing as tenant self-service (T8, T11), 1
live-but-structurally-orphaned real implementation waiting to be connected (the T8 angle logic
itself).**

---

## Architectural decisions already locked, as referenced/quoted across these 8 tasks

*(ADR-2026-038 itself remains absent from this repo — confirmed AA-438-01, not re-confirmed
here. Everything below is quoted or closely paraphrased from what each task's prompt cited from
it; sections not quoted in any AA-439 task are not summarized here rather than guessed at.)*

- **§0.1 (amend §10.3, 22/08)**: T3's escalate-and-stop behavior reversed to escalate-and-
  continue — "escalate-and-stop broke the single-job T2→T3→T5 chain AA-425 built." Shipped as
  AA-436, confirmed live (01, 06).
- **§0.2**: "AA does not gate tenant content at any step in the T0-T11 chain. AA only controls
  via two layers: (1) rate limit/quota set at tenant creation (limits volume, not a content
  approval), and (2) A4 Cross-Tenant Oversight — post-hoc monitoring with intervention capability,
  not a pre-publish gate." Directly drove AA-440's Quarter Plan/Marketplace admin→self-service
  reversal, and is the lens this audit repeatedly applied to Gate B (T7) and the trust ramp (T8)
  without this audit itself deciding either outcome (AA-440, 06).
- **This task's own framing** (not independently verified against an ADR section number by this
  audit, reported as stated): Nghiep has already decided, based on AA-439-06/07's findings, to
  **rewrite T8** rather than port `acp_s4_social` as-is, and to **keep the trust ramp** mechanism
  for T8/delivery rather than skip straight to `veto_window_auto` for every tenant.
- Sections §0.3-§0.5 were never quoted or referenced in any AA-439 task prompt — **not
  summarized here**, since nothing in this audit's own reading covers their content.

---

## Reports index

- `AA-439-01-t0-t1-audit.md` — Brand Setup → Tour Selection; resolved the ADR's T1
  contradiction; live hash-verification of running code.
- `AA-439-02-t3-t4-audit.md` — Tenant QA Gate → My Catalog; confirmed T4/T6 have no
  cross-navigation.
- `AA-439-03-t5-t6-dfs-scoring-audit.md` — Atomize → Atom Curation, DFS-scoring focus; confirmed
  `score_distinctiveness()` was never built, traced the downstream effect on Quarter Plan/N6.
- `AA-439-04-dfs-distinctiveness-combine-research.md` — pure reading task; confirmed no combined
  DFS+distinctiveness design exists in the original spec.
- `AA-439-05-dfs-usage-pattern-audit.md` — real DFS call level/frequency/persistence/cost, for
  the eventual combined-score design.
- `AA-439-06-t7-t8-audit.md` — Content Planning → Angle Gate; confirmed no T7→T8 connection in
  code; found the real (unused) angle-generation implementation; found the trust ramp's
  automatic half is dead code and has never been exercised.
- `AA-439-07-s4social-workflow-comparison.md` — precise line-by-line comparison of
  `acp_s4_social` against the real original 11-step workflow; corrected the trust-ramp-origin
  question from 06.
- `AA-439-08-t9-t10-t11-audit.md` — Final Write → Quality Pass → Publish; confirmed T9/T10 real
  (correcting a stale docstring), T11 cleanly absent.

## Explicitly open items carried forward (not this audit's job to resolve)

- ADR-2026-038's actual text (§0.3-§0.5 and beyond) — never found in any of the 4 repos; would
  need a Notion/Linear lookup outside this environment, same open item AA-438-00-SUMMARY already
  carries.
- Designing T8's rewrite, the Gate-B removal for T7, or a combined DFS+distinctiveness atom
  score — all explicitly deferred to dedicated follow-up work, not this audit's job.
- Extending channel adaptation (E3) beyond facebook/tiktok to the other 5 channels
  `Channel Output Structures.xlsx` describes.
- The `acp_deliver.tenant_tour_pages` 0→87-row and `published_tours` 72→71-row discrepancies
  (the latter from AA-438-03) — both flagged, neither chased down.
- Whether `acp_shared.usage_log`'s complete absence from the schema blocks anything else besides
  delivery accounting — not investigated beyond confirming the table doesn't exist.
