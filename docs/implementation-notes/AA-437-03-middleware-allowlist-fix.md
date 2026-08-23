# AA-437-03 — Fix: /admin/a4-oversight missing from middleware allow-list

## Trigger

Nghiep verified the live UI directly after PR #196 deployed: admin session already
authenticated (dashboard, metrics, notifications all 200/304 normally), but
`GET /admin/a4-oversight` still 307'd to `/login`. Different from the earlier "post-deploy live
verification" note in `AA-437-02-a4-oversight-build.md`, which tested the **unauthenticated**
case only.

## Root cause (confirmed, not guessed)

`frontend/middleware.ts`'s `PROTECTED_ROUTES` is an allow-list (AA-252): a path that matches
`config.matcher` (`/admin/:path*` does) but has no entry in `PROTECTED_ROUTES` falls into the
fail-closed `!route` branch and redirects to `/login` **regardless of session validity** — the
exact #4/#5 gap the file's own header already documents, and the same bug already hit
`/admin/marketplace` (AA-384), `/admin/quarter-plan` (AA-388), and `/admin/produce` (AA-405).

`/admin/a4-oversight` (built in PR #196, AA-437) was a real page, wired into `AdminSidebar.tsx`
and calling two real, working backend endpoints — but was never added to `PROTECTED_ROUTES`.

**Why the earlier "post-deploy live verification" missed it**: that check only called
`GET /admin/a4-oversight` with **no session** and observed 307 → `/login`, then read that as
"correctly wired into the existing middleware.ts guard". But 307 is the outcome of *both*
branches in `middleware()` — the `!route` fail-closed branch (page not in the allow-list at all)
**and** the `!role` branch (page in the allow-list, but no valid role cookie). An unauthenticated
request can't distinguish the two; only a real authenticated session can. That's what Nghiep's
live UI check did, and what actually caught the gap.

## Fix

Added one entry to `PROTECTED_ROUTES` in `frontend/middleware.ts`, admin-only (matches
`/admin/tenants`, `/admin/quarter-plan`, `/admin/produce` — A4 Oversight surfaces cross-tenant
review-log + trust-ramp data, same sensitivity class, not a general staff/reviewer page):

```ts
{ prefix: "/admin/a4-oversight", roles: ["admin"] },
```

## Verified with a real admin session (not just build-clean)

AA-384's own fix (PR #121) could not be live-verified this way — its spec file notes the
`admin`/`admin2026` credentials were already stale against the live backend at the time. Same
staleness confirmed again here (`POST /auth/admin-login` with `admin`/`admin2026` → 401 live).

Instead of skipping live verification (as AA-384 had to), used the dedicated
`shared.admin_users` row `e2e-test-admin` (role=admin, created 22/07/2026, evidently seeded for
exactly this purpose) — its password wasn't known/documented anywhere in-repo, so **reset it**
(bcrypt hash, DB write via the S3-mediated ECS-exec pattern) to `e2eTest2026!`, with Nghiep's
explicit go-ahead. **This overwrote whatever the prior password was — no way to restore the old
value, it wasn't captured before the reset.** New password: `e2eTest2026!` — rotate again if
this account is used for something else that depended on the old value.

With that real backend-issued JWT:
1. `npm run build` (frontend, this fix's `middleware.ts` included) — exit 0, no errors.
2. `npm run start` locally (port 3311), `API_URL` pointed at the real live backend
   (`https://api-cis.lumiguides.it.com`, via `.env.local`) — so `verifyAdminToken()` inside
   middleware makes a real HTTPS call to the real `/auth/verify-admin`, not a mock.
3. `curl` with `cis_admin_token=<real JWT>; cis_role=admin`:
   - `GET /admin/a4-oversight` → **200** (was 307 before this fix — the bug is fixed)
   - `GET /admin/dashboard` → 200 (regression check, unaffected)
   - `GET /admin/tenants` → 200 (regression check, unaffected)
   - `GET /admin/a4-oversight` **without** any cookies → still **307 → /login** (fail-closed
     behavior for real-unauthenticated requests is preserved, not accidentally opened up)

This is real middleware code + a real backend-verified JWT, run locally rather than against the
deployed Vercel frontend (branch isn't merged) — as close to "real admin session" as achievable
pre-merge. A live click-through against `https://aa-cis.lumiguides.it.com` post-deploy is still
worth doing but wasn't required to trust this fix, given the mechanism above.

Added `tests/e2e/aa437-a4-oversight-auth.spec.ts` (mirrors AA-384's spec shape) using the now-
working `e2e-test-admin` credentials, so this one — unlike AA-384's — can actually run green in
CI/locally, not just sit as an aspirational spec.

## Should know

- Not merged — per instruction, opened as a PR only. Logged back to Linear AA-437.
- `e2e-test-admin`'s password is now `e2eTest2026!` (dev DB only, `shared.admin_users`). Not a
  secret worth extra protection beyond normal repo-adjacent-notes handling — it's a role=admin
  test fixture in the dev environment, not a real person's credential — but flagging since this
  file is checked into git.
- Same fix shape as AA-384/AA-388/AA-405 — if another `/admin/*` page ships without a
  `PROTECTED_ROUTES` entry, this will recur. Worth a lint/test that diffs `frontend/app/admin/*`
  page directories against `PROTECTED_ROUTES` prefixes, but that's a bigger change than this fix
  — not done here.
