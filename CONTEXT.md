# AA-CIS-App — Content Pipeline Domain

The Master Content → Tenant Content pipeline: how one tour becomes the platform's shared master
content (Admin, A-series), and how a tenant turns a picked tour into channel-specific published
content (Tenant, T-series). Built AA-539 (06/09/2026), after AA-527 shipped a page that mixed up
this exact boundary from having no single written glossary. Other subsystems (Excel ingestion,
LLM/model routing, marketplace/billing, legacy N0-N8) are out of scope for this file — split into
their own `CONTEXT.md` under a `CONTEXT-MAP.md` if/when they need one.

## Language

### Master content (Admin side)

**Atom**:
One concrete, verbatim-derived place-and-activity pair from a tour's itinerary text (`place` +
`action`) — never a summary, paraphrase, or invented detail. Generated once, platform-wide, at
A3 (see Pipeline Stages) — not per tenant.
_Avoid_: fact, moment, detail.

**Facts Entry (platform scope)**:
One hand-written, sourced claim not present in any tour's itinerary text (price, season, visa
requirement, typical transfer time) that AA-admin writes ONCE for every tenant to cite from.
Distinct from Facts Entry (tenant scope) below — same table (`acp_shared.facts`), `scope` column
tells them apart, never merged.
_Avoid_: Fact (bare), reference data.

### Tenant content (per-tenant, built once a tenant picks/rewrites a tour)

**Segment**:
A group of Atoms (usually from different tours) that describe the same real-world moment,
matched deterministically on place-token-similarity + verb-match on action — never an LLM/
embedding call, because `segment_id` must stay stable across re-runs. Built per tenant, from that
tenant's own picked/rewritten tours — NOT a single platform-wide Segment set (see the flagged
contradiction under Open Questions).
_Avoid_: cluster, group, topic.

**Score** (Atom Ranking):
The rank-sum of a Segment's three demand/relevance signals, computed once a tenant's Segments
exist. Persisted on `acp_contract.atom_ranking`; every downstream consumer (Route, Slate) reads
this value, never recomputes it.
_Avoid_: rank, weight, priority.

**Route**:
A consecutive-day span (2-5 days) of one tour's ranked, non-excluded Segments — a Blog-only
concept (the only channel scored at Route grain instead of Segment grain). Rebuilt whole
(delete+insert) on every re-run; never accumulated.
_Avoid_: itinerary segment, leg, journey (that's Hub).

**Hub**:
The marketer's unit of choice: a persistent, human-named journey ("Nakasendo Way: The Kiso
Valley from Kyoto") that a family of Routes belongs to. Persists across Route rebuilds — reused
by `route_detection.py` when the same tour-id family regroups, never deleted, even when
orphaned (no Route currently maps to it), because a Subject that already snapshotted the name
still needs it to mean something.
_Avoid_: journey, family, group (Route Family, a distinct upstream concept, has no column here).

**Subject**:
One proposable (Segment or Route) × Channel pair, with a `state` (proposed/picked/used/cut), a
`score` (copied from Atom Ranking or Route.score, never recomputed), and `cleared_bar_reason`
(why it passed/failed that Channel's numeric Bar). One row = one thing a tenant can pick.
_Avoid_: proposal, candidate, slot (Slot is the older, deprecated N7 term — do not reuse).

**Slate**:
The tenant-facing mechanism/screen that proposes Bar-cleared Subjects for a Channel. Currently
Bar-check only (deterministic threshold pass/fail per Channel) — has NO Debate/reasoning layer
(no "why this beats that Subject" narrative); a known, deliberate gap, not a bug to silently fix.
_Avoid_: Weekly Slots (the pre-AA-511 name — fully replaced, never use again).

**Goal**:
One of a fixed 8-value list (name/description/logic/marketing_term, e.g. "Promotion" →
AIDA) a tenant picks before writing — verbatim from Nghiệp's own "Bang 1" table, not invented.
_Avoid_: objective, intent, campaign type.

**Angle**:
One of 3 LLM-generated framing options (name/why_it_works/formula_fit/best_final_style) offered
per (Subject, Channel, Goal) — the tenant picks one before Write runs.
_Avoid_: approach, take, framing (used loosely elsewhere; Angle is the specific picked object).

**Gate**:
An automated pass/fail check run inline right after Write (T9/T10) — up to 9 for `channel=
'blog'`, 6 for the other 7 channels. Each Gate is `blocking` (fails the Piece, up to 1 rewrite
before it's held) or non-blocking/`flag`-only (visible, never blocks) — never assume "failed a
gate" means "held," check `blocking` first.
_Avoid_: check, validator, rule (Gate is the specific automated-check object; "rule" is generic).

**Piece**:
One row of generated content for one (Subject, Goal, Angle) — carries `attempt_number` (max 2),
`gate_ledger` (every Gate's result on the persisted attempt), `status`
(`approved`/`held`/`failed`), and (blog only) a `publish_log` row once T11 ships it.
_Avoid_: post, draft, content (all used loosely elsewhere; Piece is the specific DB row).

**Channel**:
One of 8 values: `blog`, `linkedin`, `facebook`, `instagram`, `tiktok`, `email`,
`landing_page`, `ads`. Each has its own Slate Bar and Gate count (blog ≠ the other 7).
_Avoid_: platform, network (Channel is this project's own term for the publishing surface).

**Facts Entry (tenant scope)**:
One hand-written, sourced claim a tenant writes for themselves only (their own pricing,
cancel/rebook terms, deals) — visible only to that tenant, never to others. Same table as the
platform-scope entry above; `tenant_id` is required here, NULL there (enforced by a DB CHECK).
_Avoid_: Fact (bare) — always say which scope.

## Pipeline stages

### A-series (Admin, master content — computed once, shared by every tenant)

- **A0 — Upload**: raw tour ingestion (`raw_tours`, `pipeline_status='ingested'`).
- **A1 — Generic Rewrite (S1)**: the admin S1 pipeline rewrites A0's raw content into
  `generated_content` with a neutral, brand-agnostic voice (see AA-535) — the shared base every
  tenant later re-voices for their own brand.
- **A2 — Admin QA Gate**: A1 rows that failed auto-validation (`status='hitl'`), reviewed via the
  Review Queue before they can reach A3.
- **A3 — Master Content Pool**: `gold_aa_internal.published_tours` — a tour is "in Master
  Content" once it lands here. Atomize (see Atom above) now fires automatically right after a
  tour is published here (AA-526, `services/export/handler.py::process_export()`), as a
  fire-and-forget background task, `owner_scope='platform'`.
- **A4 — Cross-Tenant Oversight**: admin-side supervision OVER tenant-published content — Trust
  Ramp (graduated autonomy per tenant) and the force-unpublish safety net (`admin_a4.py`). Not
  part of the A0→A3 production line; it watches T-series output instead.

### T-series, old (Tenant rewrite tour, T0-T4)

- **T0 — Brand Identity**: tenant sets up their own brand voice/rules (`/portal/t0-brand`).
- **T1 — Tour Selection / Rewrite trigger**: tenant picks an A3 (Master Content) tour and fires
  the rewrite (`/portal/t1-rewrite`, `PoolTab.tsx`'s "Rewrite" button).
- **T2 — Rewrite (execution)**: the actual LLM rewrite of the picked tour into the tenant's own
  brand voice — no dedicated UI route, runs as part of T1's trigger.
- **T3 — QA Gate**: automatic validate→repair loop (max 2 repairs) on T2's output — no manual
  tenant approval step; `status='approved'` is T3's own automatic result, not a button.
- **T4 — Pool**: the tenant's own rewritten-tours pool (`/portal/t4-pool`) — a T3-approved tour
  here is what a tenant can build T7+ content from.

### T-series, new (per-tenant social content, ported from Ms. Thư's `aa-social-media`, T5-T11)

- **T5 — Atomize**: **historical label, superseded.** Originally a tenant-triggered, per-tenant
  atomize step; AA-526 (05/09/2026) moved atom generation to A3 (platform-wide, admin side, see
  above) and removed the tenant-triggered endpoint entirely. Do not build anything new against
  "T5" as a tenant-facing stage.
- **T6 — Atom Curation**: **historical label, superseded.** Was a tenant-facing atom star/delete
  UI (`/portal/t6-atoms`); removed at AA-527, replaced by the admin-only `/admin/atom-curation`
  page (platform-scope atoms only — this is exactly the page AA-527 built into the wrong role
  the first time, which is why this glossary exists).
- **T7 — Planning**: tenant-scoped Segment/Route/Score computation + slot-grid
  (`/portal/t7-planning`) — the first REAL per-tenant stage once a T4 tour has A3 atoms to build
  from.
- **T8 — Angle Gate**: Goal + Angle selection (`/portal/t8-angle-gate`, one continuous wizard
  covering T8 and T9 together — no separate T9 route).
- **T9 — Write**: Piece generation, fires automatically the instant an Angle is chosen.
- **T10 — Quality Gates**: inline within T9 (not a separate request) for the automatic Gate run;
  a tenant-facing review screen for held Pieces exists separately at `/portal/t10-review`
  (AA-501).
- **T11 — Publish**: tenant-facing WordPress publish, blog Channel only today
  (`/portal/t11-publish`); the other 7 Channels have no publish step built yet.

## Open questions (found while building this glossary — needs Nghiệp's decision)

1. **Segment/Route/Score scope contradicts this issue's own boundary statement.** AA-539's own
   description says Atomize→Segment→Research/DFS→Score→Route/Hub all belong to Admin, "computed
   once for the whole Master Content." But AA-526 (the day before, 05/09/2026) has Nghiệp's own
   confirmed, already-shipped decision on record: only the Atom is platform-wide/computed-once —
   Segment, Score (Atom Ranking), and Route/Hub are each built PER TENANT, the first time that
   tenant picks/rewrites a given tour (`atom_segment.tenant_id`/`atom_ranking` are real per-tenant
   FKs, confirmed in code and in `docs/implementation-notes/AA-526.md`'s own STEP0 correction #3).
   This glossary documents the AA-526 reality (it's what's live and tested) — **flagging, not
   silently resolving**, since it directly contradicts the wording Nghiệp just wrote into AA-539.
   Recommend this be the first question in the `/grill-with-docs` pass on the Admin/Tenant UI
   epic spec.
2. **T5/T6 labels are now historical/dead** (see above) — any UI epic spec that still refers to
   "T5" or "T6" as a tenant-facing stage should be corrected to "A3 atomize" / "admin atom
   curation" respectively before build starts.

## Related documents

- `docs/investigation/aa-social-media-audit.md` — the field-by-field comparison against Ms.
  Thư's origin repo (Segment/Route/Slate/Subject/Piece) this glossary's Tenant-side definitions
  are grounded in.
- `docs/adr/0001-atoms-platform-wide-segments-per-tenant.md` — the ADR for Open Question 1's
  underlying (already-shipped) decision.
- `docs/implementation-notes/AA-526.md`, `AA-527.md`, `AA-529.md` — build records for the A3
  atomize move, the admin atom-curation page, and Facts Entry respectively.
