# AA-439-01 — Audit T0→T1 (Brand Identity Setup → Tour Selection)

First task of the Tenant tier audit (AA-439). Audit only, no code changed. Branch
`feature/aa-439-tenant-tier-audit`, created from `main`. Every claim below is backed by
`path:line`, a real query, or a real live-verification method (SHA-256 hash comparison between
the local repo and the actual file running in the ECS container — see §3). AA-438 (Admin tier)
and AA-440 (Marketplace/Quarter-Plan migration prep) reports were read for context, not
re-audited.

**Headline: the ADR's two seemingly-contradictory statements about T1 are resolved — code
confirms AA-425/AA-436's "Done, no new endpoint" framing is accurate and current; the "T1 mới
phải là endpoint hoàn toàn mới" framing describes a state that no longer exists (superseded, not
current). T0's AA-424 fix is confirmed still in place, live-hash-verified — but a real,
currently-live gap survives that's more severe than the ADR's own framing suggests (see §1).**

---

## 1. T0 (Brand Identity) — route, auth, and the AA-424 fix

**Route confirmed**: `/portal/t0-brand` (`frontend/app/(tenant)/portal/t0-brand/page.tsx`),
label "Brand Identity" in `Sidebar.tsx:28` — renders `<BrandTab />`
(`_components/BrandTab.tsx`).

### 1a. GET/POST — AA-424's fix is real and still in place today

`BrandTab.tsx:45,63` calls `/api/tenant/admin/brand-identity` for both GET and POST — its own
header comment (`:2-7`) documents exactly why: *"was `/api/admin/brand-identity`, which
`requireAdmin()`-gated and 401'd every real tenant session... Routed through the tenant proxy so
`cis_tenant_token` reaches the now tenant-JWT-aware backend endpoint."*

Backend confirmed (`api/routers/admin_pipeline.py:4101-4193`):
```python
def _resolve_brand_tenant_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_brand_identity_bearer),
    x_admin_secret: str = Header(None),
) -> str:
    if credentials is not None:
        payload = verify_jwt(credentials.credentials)
        return payload["sub"]              # real tenant JWT → real tenant_id
    verify_admin_secret(x_admin_secret)
    return _AA_INTERNAL_TENANT_ID           # only when no Bearer token at all
```
`GET /brand-identity` and `POST /brand-identity` both depend on this resolver — **confirmed not
hardcoded for a real tenant caller.** A genuine second fix is bundled in the same commit (per
its own comment, `:4180-4185`): the INSERT was missing `brand_name` (NOT NULL since migration
044), 500ing on every real POST — found and fixed "because this is the first time POST got
exercised end-to-end against a real tenant_id here," i.e. AA-424 really was tested against live
data, not just read.

### 1b. Upload — confirmed still broken, and more severely than the code's own comment admits

`BrandTab.tsx:8-10`'s own comment already flags this honestly: *"unchanged — AA-424 scope was
GET/POST only; this one still hardcodes AA-internal tenant_id server-side, tracked as a
follow-up, not fixed here."* Confirmed in the backend (`admin_pipeline.py:4196-4214`):
```python
@router.post("/brand-identity/upload")
async def upload_brand_file(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    tenant_id = "00000000-0000-0000-0000-000000000001"   # hardcoded, no JWT path at all
```

**But this task's own investigation found the gap is worse than that comment describes.**
`BrandTab.tsx:86`'s `handleUpload()` calls `fetch("/api/admin/brand-identity/upload", ...)` —
**not** the tenant-proxied `/api/tenant/*` path used by GET/POST, but the plain
`/api/admin/[...path]` catch-all proxy. That proxy's `requireAdmin(req)`
(`frontend/lib/auth-server.ts:27-31`) reads the `cis_admin_token` cookie — a real tenant session
only ever sets `cis_tenant_token` (per `Sidebar.tsx`'s own `logout()`), never `cis_admin_token`.
`requireAdmin()` returns `{ok: false, response: unauthorized()}` immediately when that cookie is
absent, **before the request ever reaches the backend's hardcoded-tenant_id code at all.**

**Conclusion: the "Upload Brand Guide" dropzone on a real tenant's T0 page does not just write
to the wrong tenant_id — it 401s outright for any real tenant session**, confirmed by tracing
both the frontend fetch target and the exact cookie `requireAdmin()` checks for. This is a real,
live, currently-existing gap, more complete than what the code's own inline comment claims — not
contradicting the ADR (which doesn't mention upload specifically), but worth flagging precisely
since a future task might otherwise assume "wrong tenant_id" is the only problem to fix.

### 1c. Real data — T0 has been used for real setup by 5 tenants

Live query (22/08 17:08 UTC): `shared.tenant_brand_rules` has rows for 5 distinct tenants —
`aa_internal` (1 version), `test-agency` (3 versions, latest updated 21/08), `aa-384-live-verify`
(2 versions), `test-n1-flow` (1 version), `aa309-verify-c5316bd4` (1 version). All 5 have
`is_active=true` on their latest version. T0's GET/POST path is confirmed genuinely exercised by
multiple test tenants, consistent with §1a's fix being real and working.

---

## 2. T1 (Tour Selection / "Browse Pool") — resolving the ADR's apparent contradiction

**Route confirmed**: `/portal/t1-rewrite` (label "Browse Pool", `Sidebar.tsx:26`) — matches the
ADR's assumed slug exactly, no guessing needed. Renders `<PoolTab />`
(`_components/PoolTab.tsx`).

### 2a. What the button actually triggers — read end-to-end, not assumed

`PoolTab.tsx:97` (`doRewrite()`): `POST /api/tenant/v1/tours/pool/${id}/rewrite`. Backend:
`api/routers/v1_tours.py::trigger_rewrite()` (`:187-435`), full function read. It:

1. Creates a `gold_aa_internal.tenant_tour_versions` row, `status='pending'`, tenant-scoped from
   the verified JWT (`tenant["sub"]`, real auth via `get_tenant`, not admin-secret).
2. Spawns a background `asyncio.create_task(_do_rewrite_and_save())` and returns immediately
   (`:425-435`, `"status": "pending"`).
3. Inside that background task, in order, **in one single job**:
   - `_do_rewrite(...)` from `v1_pipeline.py::_rewrite_tour()` — **T2**, the actual LLM rewrite
     (same engine the admin S1-Rewrite pipeline uses, called with `is_tenant_rewrite=True`).
   - `run_t3_qa_gate(...)` from `services/acp_produce/tenant_pipeline.py` — **T3**, the grounding
     + structural QA gate, up to `TENANT_QA_MAX_REPAIRS` self-repair rounds.
   - Writes `tenant_tour_versions.qa_status`/`qa_repair_count`/`qa_auto_passed` (`:367-380`).
   - `escalate_t3_failure(...)` when QA didn't clear (`:387-396`) — writes a `review_queue` row
     for later oversight (A4/AA-437), but **per AA-436 (yesterday, 22/08) this no longer stops
     the chain** — confirmed by the code comment right there: *"T3 no longer escalate-BLOCKS...
     the chain now continues to T5 below unconditionally instead of stopping here."*
   - `run_t5_atomize(...)` from the same `tenant_pipeline.py` — **T5**, atomize with
     `owner_scope=tenant_id` — confirmed to run **unconditionally**, real pass or auto-pass
     alike (AA-436 removed the old branch that skipped it on failure).

**This is the full T2→T3→T5 chain, confirmed running end-to-end inside the SAME endpoint T1's
"Rewrite" button has always called — not a new endpoint.**

### 2b. Resolving the ADR's contradiction — verified, not reconciled by assumption

The ADR (per the task's own quoting) contains two statements that read as contradictory:
- §10.4/11.2: T1's "Rewrite" button is "100% Lane A/S1 cũ... hoàn toàn tách biệt N7/atom
  pipeline" — implying no T2-T5 chain exists yet, a new endpoint is needed.
- §11.1/11.2: AA-425 is "Done — nối thẳng vào `_rewrite_tour()`/PoolTab, không cần endpoint
  mới" — implying the chain already runs inline.

**Verified against real, live code: the second statement is accurate and current; the first
describes a state that has been superseded.** `_rewrite_tour()` (T2's LLM call) is indeed the
same "Lane A/S1" engine — that half of the first statement is still literally true — but it is
**not** "hoàn toàn tách biệt" from the atom pipeline anymore: the same background task that
calls it also runs T3 and T5 in sequence, confirmed by the code just read. The first ADR
statement is stale, most plausibly written before AA-425 shipped and never corrected once the
later section was added — **this is a real, confirmed internal inconsistency in the ADR
document itself, not something this audit resolved by picking a side**; it's flagged here
exactly as found, per the task's own instruction not to silently reconcile it.

### 2c. Confirmed this IS the currently-deployed, currently-running code — not just what's in the repo

Two independent live checks, not inference:
- **ECS task definition**: the running task is `aa-cis-dev-api:121`
  (`aws ecs describe-tasks`), started `2026-08-22T21:49:23+07:00` — 4 minutes after AA-436's
  merge commit (`71a045c`, `2026-08-22 21:45:30 +0700`) — matching AA-436's own post-deploy
  verification note exactly (`docs/implementation-notes/AA-436-t3-autopass.md`: *"ECS
  (aa-cis-dev-api:121, rollout COMPLETED)"*). No commit has landed on `main` since.
- **Byte-identical file hash**: `sha256sum` of the local repo's `api/routers/v1_tours.py`
  (`a2a6bca6...fdec15`) matches, byte-for-byte, the same file read live from inside the running
  ECS container (`/app/api/routers/v1_tours.py`, same hash) — confirmed via ECS exec. **What was
  read in §2a is exactly what is running in production right now, not a stale repo snapshot.**

### 2d. Did AA-436 itself already do the live test this task's step 6 asked for? Yes — cited, not repeated

`docs/implementation-notes/AA-436-t3-autopass.md`'s "Post-deploy verify" section (real, already
on disk, dated 22/08 after merge) already did precisely what this task's step 6 asks: minted a
real JWT for a fresh temp tenant, called the live public API
(`POST https://api-cis.lumiguides.it.com/v1/tours/pool/{id}/rewrite`), confirmed
`qa_auto_passed:true` through the real gateway + real ECS + real DB, confirmed the badge renders
on the **real production frontend** (`https://aa-cis.lumiguides.it.com`), then deleted the temp
tenant and all its rows, confirmed clean.

**This task did not repeat that exact live test** — doing so would create new temp data and
verify nothing that isn't already verified, hash-confirmed (§2c), and documented with real
request/response evidence. Per the task's own guidance to say clearly when a live test wasn't
independently repeated: **not repeated here, because an equivalent, thorough, real live test
already exists and was cross-checked instead** (§2c's hash/task-def check confirms it's still
the same code running, not stale evidence from a prior deploy).

---

## 3. T4 ("My Catalog") — does it show T3/T5 results? Partially, confirmed by reading the actual component

The ADR's "chưa hiện kết quả T3/T5 cho tenant" (§11.2) needed a precise re-check, since AA-436
shipped *something* on this exact question the day before this audit.

`frontend/app/(tenant)/portal/_components/CatalogTab.tsx:624-636`:
```python
function QaAutoPassBadge() {
  return <Badge variant="info">Extra QA pass</Badge>;
}
```
Rendered next to `StatusBadge` in both the list row and the detail panel header
(`:403-404`, `:435-436`), conditional on `v.qa_auto_passed`/`selected.qa_auto_passed`.

**Confirmed: the ADR's blanket claim is now partially outdated** — a T3-derived signal (the
"Extra QA pass" badge) is shown to the tenant today, but **only** for the auto-pass case; a
clean T3 pass shows no badge at all (same visual as a real pass — this is intentional, per the
component's own comment: *"an auto-passed high-score tour reads identically to a real high-score
pass from the tenant's side... the badge is the only visible difference"*). **T5's result (atom
count/success) is not shown on T4 at all** — grepped the whole file for atom-related rendering,
none found; T5's output is only reachable via the separate `/portal/t6-atoms` (Atom Curation)
page, a different route entirely. So: T3 → partially surfaced (only the auto-pass edge case);
T5 → not surfaced on T4 at all, confirmed. The badge's label text is itself still explicitly
unconfirmed with Nghiep, per the component's own comment (`:633-634`) — an open item, not
something this audit resolved.

---

## 4. Real DB state (task step 5)

Query run 22/08 17:08 UTC:

```
tenant_brand_rules: 8 rows across 5 tenants (detail in §1c)

tenant_tour_versions: 23 total, ALL edit_source='ai_generated' (100%),
                       ALL 23 have qa_status IS NOT NULL (0 with qa_status NULL)
  by status:    needs_review=12, approved=8, rejected=2, ai_generated=1
  by qa_status: pending=11, escalated=11, passed=1
  qa_auto_passed=true: 0 rows (every single row shows false, including all 11 'escalated' ones)

by tenant:
  test-agency (9fb0a3db-...):    13 rows, 2026-08-21 12:14 → 15:40 UTC
  wanderlux-travel:               8 rows, 2026-05-12 → 2026-05-14
  wildkind-travel:                2 rows, 2026-05-19

tour_atoms by owner_scope: platform=2551 (unchanged from AA-438/440), 
                           9fb0a3db-...(test-agency)=15, latest 2026-08-21 15:40
```

**No `edit_source` column value distinguishes an "old Lane A only" row from a "full T2-T5
chain" row** — every row is `'ai_generated'`, and `qa_status` is populated on all 23 rows
regardless of when they were created (including the May rows, which predate T3/T5 entirely by
about 3 months) — meaning `qa_status`'s presence alone cannot be used to date a row against the
T3 rollout; it does **not** cleanly separate "went through the old Lane A path" from "went
through the new T2→T3→T5 chain." **The one column that does distinguish them is timing against
the AA-436 merge** (`2026-08-22 21:45:30 +0700`): every one of these 23 rows was created before
that merge, so **none of them were produced by the exact currently-deployed auto-pass-and-
continue logic** — they're leftover data from earlier test sessions (consistent with `qa_auto
_passed=false` on all 11 escalated rows: under the pre-AA-436 code, that field either didn't
exist yet or was never set to true, since the old code stopped the chain instead of continuing
and flagging). **This is not a live bug** — it's explained entirely by data age, confirmed by
comparing row timestamps against the merge commit timestamp; AA-436's own post-deploy
verification (§2d) already produced (and then deleted) a real post-merge row showing
`qa_auto_passed=true` correctly. This leftover pre-merge test data (mostly under `test-agency`)
is exactly the kind of "build/test data" the AA-438 summary's Data Cleanup Plan already
anticipates clearing.

---

## Summary

| Question | Answer |
|---|---|
| T0 route | `/portal/t0-brand`, confirmed |
| T0 AA-424 fix still in place? | **Yes, confirmed live** (JWT-first resolver, `admin_pipeline.py:4101-4114`) |
| T0 fully fixed? | **No** — upload endpoint still hardcoded AND 401s outright for real tenants (worse than its own comment states) |
| T1 route | `/portal/t1-rewrite`, confirmed |
| T1 "Rewrite" triggers old Lane A only, or full T2→T3→T5? | **Full T2→T3→T5 chain, confirmed live** — same endpoint, no new route |
| ADR contradiction | Real — one section is stale (pre-AA-425), the other (AA-425/436 "Done") is current and verified; not silently resolved, both stated |
| Is this the code actually running right now? | **Yes** — ECS task-def + SHA-256 file-hash both confirmed live |
| T4 shows T3/T5 results? | T3: partially (auto-pass badge only). T5: not at all (only visible via separate T6 page) |
| DB distinguishes old vs. new lane? | No column does directly; timing against the AA-436 merge does — all 23 existing rows predate it |

## Open items — explicitly unconfirmed / out of scope

- The exact fix for T0's upload endpoint (tenant-JWT path + real tenant_id) — named, not
  designed or implemented here (no code changes this task).
- The "Extra QA pass" badge label text — explicitly unconfirmed with Nghiep per the component's
  own comment; not resolved here either.
- Whether T5's atomize result should be surfaced on T4 itself (vs. staying T6-only) — not
  decided, flagged as a real gap per the ADR's original ask.
- Full A4 (AA-437) read path for the `review_queue` rows `escalate_t3_failure()` writes — out of
  scope for this task (T0→T1 only); AA-436's own STEP0 doc already found the 2 existing
  `review_queue` read endpoints are both wrong for this (neither is T3-aware) — not re-verified
  here, just noted as a pointer for whoever audits A4.
