# AA-437-02 — Build A4 Cross-Tenant Oversight v1

**Post-merge update (23/08/2026):** PR #196 merged to `main` (`6652a66`) after CI green
(Nghiep's go-ahead). `Deploy Dev` green (Vercel + ECR build + Lambda + ECS Dev all `success`) —
image digest confirmed matching ECR `:latest` exactly, ECS steady state 1/1. Both endpoints
re-verified as real HTTPS calls against the live deployed backend (not local/tunneled calls) —
see "Post-deploy live verification" at the bottom.

Branch: `feature/aa-437-02-a4-oversight-build` (off `main`, post AA-443 merge).
Follows STEP0 (`docs/claude_audit/AA-437-01-a4-step0-audit.md`) — no re-investigation done, per
task instructions.

## Decisions (Nghiep's 5, applied as given — not re-litigated)

1. Both use cases (review-log + trust-ramp) built together, read-only. No flag/suspend/
   force-unpublish — deferred to Command Center backlog (AA-255→259).
2. Trust ramp shows current state only. No `suggest_ramp_transition()` automation, no
   `engagement_ok`/`weeks_active` formula designed — STEP0 already confirmed neither exists
   anywhere in the codebase; out of scope here too.
3. No per-tenant single ramp "level" — every `acp_deliver.packets` row shown with its own
   `publish_mode`, grouped visually by tenant on the FE, never collapsed to one value.
4. Route: `/admin/a4-oversight`.
5. Two endpoints: `/admin/a4/review-log`, `/admin/a4/trust-ramp` — new router
   (`api/routers/admin_a4.py`), not a patch to either existing `review_queue` reader (both
   `INNER JOIN generated_content`, structurally incompatible with T3 rows — STEP0/AA-436 finding).

## Changed

- New: `api/routers/admin_a4.py` (2 endpoints), registered in `api/main.py`.
- New: `frontend/app/admin/a4-oversight/page.tsx`.
- `frontend/app/admin/_components/AdminSidebar.tsx`: added "Cross-Tenant Oversight" nav item
  (admin-only group, next to Run Health).

## Tradeoffs

- `review-log`'s check_id pattern rollup is computed **client-side** (raw rows from the backend,
  `useMemo` count on the FE) rather than a server-side `GROUP BY` — per the task's own guidance
  ("chọn cách đơn giản hơn, ít logic hơn ở BE") and STEP0's finding that a plain group-by is
  enough at current volume (52 total rows). If volume grows into the thousands this becomes a
  performance question, not a correctness one — not addressed here.
- `trust-ramp` does a `LEFT JOIN shared.tenants t ON t.tenant_id::text = p.tenant_id` (packets'
  `tenant_id` is `TEXT`, tenants' is `UUID`) — a cast, not a schema change; matches the existing
  convention `admin_produce.py`/`acp_health.py` already use for this exact join shape.
- No pagination on `trust-ramp` (4 real rows today, STEP0 confirmed only one tenant has any
  packets at all) — would need one before real B2B tenants accumulate packets, not needed for v1.

## Should know

- `api/routers/admin_a4.py::_parse_jsonb()` defensively parses `escalate_detail` — this app's
  connections have no jsonb codec registered (same AA-314/AA-425 gap noted elsewhere), so it can
  arrive as a raw JSON string rather than a decoded list/dict depending on call path.
- The seed row created in Step 0 (see below) was deliberately triggered through the **real**
  T1→T2→T3 HTTP endpoint (`POST /v1/tours/pool/{id}/rewrite`), not written directly to the DB —
  it's the first real, live example of AA-436's `qa_auto_passed=true` write path (STEP0 had
  flagged this as untested — all 11 prior rows predated AA-436's fix).

## Step 0 — seed data (real QA-fail-twice row)

- Used the real, active test tenant `test-n1-flow` (`6fbaf284-e3cd-4b4b-b53b-c9a04e8fae8e`).
  Temporarily set its `shared.tenant_brand_rules.forbidden_words` to `["tour", "day"]` (v2,
  active) — words virtually guaranteed to appear in any tour-itinerary rewrite, guaranteeing
  `FORBIDDEN_WORD` fires on the initial attempt and both repair rounds.
- Triggered a real rewrite via live HTTP: `POST https://api-cis.lumiguides.it.com/v1/tours/
  pool/2ac8b5a2-6a73-4b32-bc00-7003838d4371/rewrite` with a real tenant JWT — the actual
  production T1 "Rewrite" trigger, not a direct function call.
- Polled `gold_aa_internal.tenant_tour_versions` until done (~40s, real Bedrock calls: 1 initial
  + 2 repair rounds). Result: `qa_status='escalated'`, `qa_repair_count=2`,
  **`qa_auto_passed=True`** — confirms AA-436's write path end-to-end, live, for the first time.
- Confirmed the matching `silver_aa_internal.review_queue` row
  (`id=8d43ea2a-4b00-4566-b10d-bf8c626d0a3d`): `tenant_tour_version_id` matches, `escalate_detail`
  contains `structural:FORBIDDEN_WORD` (the intentional trigger) + `structural:META_TOO_SHORT`
  (incidental, from the same generation). T3-style row count went 11 → 12.
- **Reverted** the tenant's `tenant_brand_rules` back to its original v1 (`forbidden_words=[]`,
  active) immediately after — the poisoned brand rules were only needed to force the failure, not
  worth leaving live on a shared test tenant. **Kept** the seeded `tenant_tour_versions` +
  `review_queue` rows as a live fixture (Nghiep's call was optional either way) — this is the
  data the endpoints/FE below are verified against.

## Verify

- `tsc --noEmit` (whole frontend project): 0 errors.
- `flake8` (project config): 0 findings on `admin_a4.py` / `main.py`.
- `pytest tests/unit/`: 1359 passed, 0 failed — no regression.
- `npm run build` (full Next.js production build): **exit 0**, `/admin/a4-oversight` compiles and
  prerenders as a static route alongside every other admin page, no errors (only pre-existing
  unrelated Sentry deprecation warnings). This is the strongest pre-deploy confirmation available
  that the page has no build-time/React errors — a live browser console check needs the branch
  deployed (no headless browser in this environment), same limitation noted in AA-443's report.
- **Both endpoints verified directly against the real dev DB** (SSM tunnel, calling the actual
  `get_review_log()`/`get_trust_ramp()` functions from `admin_a4.py` — not mocked, not
  re-implemented):
  - `get_review_log()`: returned **12** rows total (was 11 before Step 0's seed) — the seeded row
    (`tenant_tour_version_id=0a839110-...`) present with full `escalate_detail`, correct
    `tenant_name`("TEST-N1-flow")/`tenant_slug` from the join. Filtering by
    `tenant_id=6fbaf284-...` correctly narrowed to **1** row (just the seeded one).
  - `get_trust_ramp()`: returned **4** rows, all `tenant_id=00000000-...-0001` (aa_internal) —
    matches STEP0's finding that only the internal tenant has any packets today. Real
    `tenant_name`("Adventure Asia Internal") joined correctly.
- Full live-HTTP verification (calling the deployed endpoints over `https://api-cis.lumiguides.
  it.com`) was **not done** — this branch isn't merged/deployed yet, so the live backend still
  runs the old code without `admin_a4.py`. Same pattern as AA-441/AA-443: full HTTP-level
  verification happens post-merge, once deployed — reported separately when that happens.

---

## Post-deploy live verification (23/08/2026, after merge)

All calls below hit `https://api-cis.lumiguides.it.com` / `https://aa-cis.lumiguides.it.com`
directly — real HTTPS, real deployed code (ECS image digest confirmed == ECR `:latest`), no
local/tunneled calls, no mocks.

- **`GET /admin/a4/review-log?limit=200`** with real `X-Admin-Secret` → **200**, `total: 12`,
  seeded row (`tenant_tour_version_id=0a839110-...`) present with full `escalate_detail`.
- **`GET /admin/a4/review-log?tenant_id=6fbaf284-...`** (the seeded tenant) → **200**,
  `total: 1` — tenant filter works live.
- **`GET /admin/a4/trust-ramp`** → **200**, the real 4 packets, all `tenant_id=00000000-...-0001`
  (aa_internal), correctly joined to `tenant_name`.
- **`GET /admin/a4-oversight`** (no admin session) → **307 → `/login`** — same auth-gated
  behavior every other `/admin/*` page has when unauthenticated (not a 404), confirming the
  route is live and correctly wired into the existing `middleware.ts` guard. A full logged-in
  browser render was not done — no headless browser available in this environment; confidence
  instead comes from the clean `next build` (pre-merge) + this redirect behavior + the two
  endpoints it calls both verified working live above.
- ECS `aa-cis-dev-api`: steady state, 1/1 running, single `PRIMARY` deployment.
