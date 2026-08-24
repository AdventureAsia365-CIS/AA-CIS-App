# AA-455 STEP0 (bước 1) — A4 force-unpublish tối thiểu: investigation

Investigate-only, same worktree as AA-455-00 (`../aa-cis-app-t11-investigate`,
`feature/t11-publish-step0`). No code changed, no migration run, no PR.

**Parallel-session check before starting**: `ListAgents` showed one busy peer session
(`aa-cis-d3`) plus the main `AA-CIS-App` directory sitting on branch
`pqnghiep1354/aa-454-4-small-fixes` — confirms AA-454 is working directly in the shared main
working tree (not an isolated worktree), matching the known "parallel sessions share git workdir"
risk. Did not touch that directory. This task's own AA-455 T11 worktree
(`../aa-cis-app-t11-investigate`) was idle, clean, and already holds the STEP0-00 report from the
prior session in this same conversation — reused it rather than creating a third worktree.

---

## 1. Linear AA-455 — full description read

Title: **"[A4+T11] Force-unpublish tối thiểu (A4) TRƯỚC, rồi T11 Publish blog-only (auto-publish,
Option B schema)"**. Status: Backlog, Priority: High, project "ACPv2 — Admin/Tenant Split (A/T)".

Nghiep's locked decisions (24/08/2026), relevant to this bước-1 task:

1. **Order**: build A4 force-unpublish minimal FIRST, T11 auto-publish SECOND — explicitly to
   avoid a window where T11 is live but AA has no way to pull content down if something goes wrong
   (grounding miss, brand-rule violation T10's gates didn't catch).
2. **T11 channel**: blog-only first (rewires the existing WordPress adapter from admin-gated to
   tenant self-service, reads `content_piece` instead of `blog_drafts`). Out of scope for *this*
   issue — noted only because it's what `publish_log` will eventually be populated by.
3. **Schema**: Option B confirmed — a dedicated `acp_shared.publish_log` table, separate from
   `content_piece`'s T10 approval state.
4. **This issue's own scope line, verbatim**: "Ghi rõ `unpublished_by`/`unpublished_at` để phân
   biệt hành động AA vs tenant tự gỡ (**nếu** tenant cũng có quyền tự gỡ — cần xác nhận thêm khi
   build, không giả định)." — Nghiep has already flagged the tenant-self-unpublish question as
   open, not decided. This task's job is to present options, not assume an answer (see §6 below).
5. Explicitly out of scope for this issue: the other 7 channels, and any A4 action beyond
   force-unpublish (flag/suspend stays deferred, per AA-437's original scope).

---

## 2. AA-455-00's Option B sketch (context, not re-derived)

Already read in full this session (produced by this same worktree/branch's prior STEP0). Relevant
columns from the sketch: `publish_id`, `piece_id` (FK `content_piece`), `tenant_id`, `channel`,
`status CHECK IN ('published','unpublished','failed')`, `external_id`, `external_url`,
`published_at`, `unpublished_at`, `unpublished_by`, `last_error`, `created_at`. Confirmed this
session (§5 below) that **no migration for this table exists yet** — the sketch is still only a
sketch, exactly as AA-455-00 labeled it.

---

## 3. A4 code as it exists today (AA-437, Done)

### Backend — `api/routers/admin_a4.py`

One router, prefix `/admin/a4`, two endpoints, **both GET, both read-only**:

- `GET /admin/a4/review-log` — T3 QA-gate escalation rows (`silver_aa_internal.review_queue`,
  `tenant_tour_version_id IS NOT NULL` only).
- `GET /admin/a4/trust-ramp` — every `acp_deliver.packets` row with its own `publish_mode`, no
  per-tenant rollup.

Auth: `verify_admin_secret(x_admin_secret)` (imported from `api/routers/admin.py`) — the
`X-Admin-Secret` header pattern, **not** the tenant-JWT `get_tenant()` pattern used by `/v1/*`
routers. Any new A4 action endpoint should follow the same auth dependency for consistency (it's
an admin-only surface by design — see file's own header: "No flag/suspend/force-unpublish here —
explicitly out of scope... deferred to the Command Center backlog").

### Frontend — `frontend/app/admin/a4-oversight/page.tsx`

One page, two sections as two components (`ReviewLogSection`, `TrustRampSection`), both fetching
via the same-origin proxy convention (`/api/admin/a4/review-log`, `/api/admin/a4/trust-ramp`) —
never the ECS API URL directly, matching the repo-wide `/api/admin/[...path]` convention. Reuses
`AdminSidebar` + `adminUi.tsx` tokens (Card, Badge, serif/mono/sans) — no new design pattern.

**The page's own header text currently states, verbatim**: *"No action on this page
(flag/suspend/force-unpublish is a separate, future scope)."* This line becomes stale the moment
force-unpublish ships — a real thing to update when building, flagged here so it isn't missed.

---

## 4. Middleware allowlist + proxy — confirmed no repeat of the AA-437 bug, IF scoped correctly

Read `frontend/middleware.ts`'s `PROTECTED_ROUTES` array. `/admin/a4-oversight` is **already** an
entry (`{ prefix: "/admin/a4-oversight", roles: ["admin"] }`), added by AA-437 itself after
hitting the exact 307-redirect bug this file's header now documents four times (AA-384, AA-388,
AA-405, AA-437 all independently hit it: a real page shipped with no allowlist entry silently
307s to `/login` even with a valid admin session).

**Consequence for this task**: if force-unpublish ships as a **third section on the same
`/admin/a4-oversight` page** (not a new route), the prefix match already covers it —
**no new middleware entry needed**. The bug only reappears if a *new* top-level admin route gets
created instead (e.g. a dedicated `/admin/a4-oversight/publish-log` page). This is itself an
argument for the "same page, new section" answer to §7 below, not just a styling preference.

Also read `frontend/app/api/admin/[...path]/route.ts` — confirmed it's a generic catch-all proxy
(`requireAdmin()` → forwards any method, including POST, to `${API_URL}/admin/${path}` with
`X-Admin-Secret` attached server-side). This route is explicitly documented as **not covered by
`middleware.ts`'s matcher at all** — it does its own independent `requireAdmin()` check. Meaning:
a new `POST /admin/a4/...` backend endpoint is reachable through this proxy with **zero proxy-code
changes**, as long as its path starts with `/admin/a4/...` like the existing two endpoints.

---

## 5. Confirmed: `acp_shared.publish_log` does not exist anywhere yet

`grep -rl "publish_log" api/migrations/` — zero hits. Confirmed absent, matching AA-455-00's own
framing (sketch only). This directly feeds the sequencing answer in §8.

---

## 6. Design question — does the tenant get to unpublish their own content? Not decided; 3 options

Re-read ADR-2026-038 §0.2 (fetched in the prior STEP0, re-checked this session) specifically for
any signal on this. §0.2 says AA controls tenant content only via (1) tenant-creation-time
rate-limit/quota and (2) A4 post-hoc oversight with intervention capability
(flag/suspend/**force-unpublish**). **This describes AA's own mechanism only — it says nothing
about whether the tenant can also pull down their own published piece.** Not a gap in reading; the
ADR genuinely doesn't address it. Per the Linear issue's own instruction, presenting options rather
than assuming:

**Option 1 — AA-only, no tenant self-unpublish (recommended for *this* issue's minimal scope)**

`publish_log` gets exactly one mutating action for now: A4's force-unpublish. No tenant-facing
unpublish endpoint at all in this PR. Matches the issue's own title ("Force-unpublish tối thiểu
(A4)") literally — the feature being built is an AA safety-net action, not a tenant self-service
feature. `unpublished_by` always holds an admin identity (mirrors `x-admin-user-id`, the same
header the existing `/api/admin/[...path]` proxy already forwards). Simplest to ship, smallest
surface, directly closes the "T11 has no undo button" risk the issue exists to fix — the tenant
self-unpublish question can be answered later, as part of T11 itself (bước 2), without touching
this PR again.

**Option 2 — Tenant self-unpublish added later, as part of T11 (bước 2), not this issue**

Same as Option 1 for *this* issue, but explicitly scopes a second, tenant-facing endpoint
(`DELETE`-style, tenant-JWT-gated) into the T11 build task instead of silently deferring it with
no owner. Precedent already exists in this codebase for exactly this shape:
`v1_competitors.py:187` — `@router.delete("/{competitor_id}")`, tenant-JWT-gated, a tenant deleting
their own row. `unpublished_by` would then need to record *which* actor type unpublished a row
(not just an ID) — see the schema note below.

**Option 3 — Both built together, in this same PR**

Full self-service (tenant unpublish via a new T11-adjacent endpoint) + AA override (A4
force-unpublish) shipped together now, sharing one `publish_log` row and one `status` state
machine. Larger surface for a "tối thiểu" (minimal) issue — probably more than this issue's own
scope line asks for, but listed because it avoids a later migration/endpoint-shape rework if
Nghiep already knows tenants will get this soon.

**Recommendation (not a decision)**: Option 1 for this issue, with one schema hedge regardless of
which option is picked later — see §8's schema note. Don't build Option 2/3's tenant endpoint now;
just don't paint the schema into a corner that makes adding it later awkward.

---

## 7. UI — third section on the existing page (not a new route)

Add `ForceUnpublishSection` (or fold the action directly into a widened `TrustRampSection`/new
`PublishLogSection`) as a **third card on `/admin/a4-oversight`**, same file, same component
pattern (`Card`, `Badge`, `TH`/`TD` from `adminUi.tsx`), fetched via
`/api/admin/a4/publish-log` (new GET, list rows) + a mutating action
(`POST /api/admin/a4/publish-log/{publish_id}/unpublish`, matching the REST-verb-on-sub-resource
shape already used elsewhere in this router file's siblings). This is a direct application of
§4's finding — not a new route, so zero middleware risk — and matches the exact "two sections,
one page, one file" pattern this page already established for review-log/trust-ramp. Remember to
update the page header's "No action on this page" line (§3) when this ships.

---

## 8. Sequencing — schema and force-unpublish action cannot ship in separate PRs; the "song song"
framing in the issue is slightly imprecise

The Linear issue's own text hedges: *"force-unpublish 1 `publish_log` row (khi tồn tại — có thể
cần build song song hoặc ngay trước bước 2 vì `publish_log` là bảng mới của T11)"* — written before
this deeper technical read. Now that the schema and code are read directly, a more precise answer:

**A force-unpublish action is meaningless without a table to act on — it cannot be built,
deployed, or even code-complete against a table that doesn't exist.** So the real dependency is
strict, not parallel-optional:

1. **The `acp_shared.publish_log` migration must be written and applied as part of *this* issue
   (bước 1)**, even though the table conceptually "belongs" to T11's future write path (bước 2).
   There's no way around this — `UPDATE acp_shared.publish_log SET status='unpublished' ...`
   requires the table to exist first, full stop.
2. **The A4 force-unpublish endpoint can then be built and deployed safely against an empty
   table** — T11 (bước 2) doesn't exist yet, so `publish_log` will have zero real rows for a
   while. The endpoint just returns 404/no-op until bước 2 starts writing rows into it. This is
   not a problem — deploying dead-but-ready code ahead of its producer is a normal, safe order
   (same shape as AA-450's `angle_gate_request.cta` column existing before AA-451 wired a real
   writer into it).
3. **Live/E2E verification of force-unpublish before T11 exists** will need a manually-inserted
   test row (same S3-mediated ECS-exec script pattern used elsewhere in this repo for one-off DB
   writes) rather than a real end-to-end publish — there's no real producer yet to generate one.
   Worth deciding at build time whether that's sufficient proof for this PR, or whether
   force-unpublish's live-verify should wait until bước 2 ships and a real row exists.

**Net recommendation**: this issue's PR should contain (a) the `publish_log` migration, (b) the A4
force-unpublish endpoint, (c) the new FE section — all together, in one PR, exactly because they
can't be meaningfully split. T11's own write path (bước 2, blog-only auto-publish) stays a fully
separate later PR that starts *populating* the table this PR creates.

---

## 9. Schema note carried forward from §6 (hedge, not a decision)

Whichever tenant-self-unpublish option Nghiep eventually picks, `unpublished_by` should probably
be typed to hold an actor-kind alongside the id from the start (e.g. `unpublished_by TEXT` storing
a prefixed value like `"admin:<admin_user_id>"` vs. `"tenant:<tenant_user_id>"`, or a separate
`unpublished_by_role TEXT CHECK (... IN ('admin','tenant'))` column) — cheap to add now, avoids a
follow-up migration if Option 2/3 gets picked later. Not building this now, just flagging it as a
one-line addition to make at migration-write time regardless of which option wins.

---

## Summary for Nghiep

- A4 today is exactly 2 GET endpoints (`admin_a4.py`, admin-secret-gated) + 1 FE page with 2 read-
  only sections — a clean, small surface to extend.
- **No new middleware entry needed** if force-unpublish stays a third section on the existing
  `/admin/a4-oversight` page (already allowlisted) — a new route would repeat the exact 307 bug
  this file's header documents four separate times already.
- Tenant self-unpublish is genuinely undecided by the ADR — 3 options above, recommend Option 1
  (AA-only for this issue, defer tenant-unpublish to T11 bước 2) with a cheap schema hedge either
  way.
- The issue's own "build song song" framing undersells the real dependency: **the `publish_log`
  migration has to ship as part of THIS issue**, not bước 2 — the force-unpublish action can't
  exist without it. Recommend one PR: migration + endpoint + FE section together.
