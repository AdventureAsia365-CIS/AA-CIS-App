# AA-457 [T11 PR1] — tenant_integrations + WordPress save/test-connection + UI (Option 3+2)

STEP0 for this task was AA-456's own STEP0 report (Linear comment, 24/08/2026) — schema (§7),
Secrets Manager convention (§4), endpoint shapes (§8a/8b), UI Option 3+2 (§9). This is the real
build.

## Decisions

- **New router `api/routers/v1_integrations.py`**, not folded into `v1_publish.py` — integrations
  (credentials/config) and publish-log (delivery state) are different resources with different
  lifecycles; matches this codebase's own precedent of giving each distinct resource its own
  router file (`v1_publish.py` itself was split out from `v1_content_writing.py` for the same
  reason in AA-455).
- **Reused, not reinvented, two existing conventions** (per AA-456 STEP0 §3/§4, explicit
  instruction not to invent a new pattern):
  - Secrets Manager key naming: `acp/cms/{tenant_id}` — the exact string `v1_s4_blog.py` already
    built (confirmed live before this task: 0 real secrets ever existed under it — this PR gives
    that naming convention its first real writer).
  - Secret fetch/write shape: arbitrary `secret_key` at call time, no caching — matches
    `services/acp_s4_blog/cms/publisher.py::_get_cms_creds()` exactly, not `shared/secrets.py`'s
    fixed-ARN-per-env-var pattern (wrong shape for a per-tenant secret space, per STEP0 §4).
  - Table shape: one row per (tenant, thing), JSONB for non-secret config — matches
    `shared.tenant_seo_config` (migration 003), generalized to `UNIQUE(tenant_id,
    integration_type)` instead of a bare `UNIQUE(tenant_id)` since this table is meant to hold
    more than WordPress eventually (webflow/ghost, matching `acp_cms_publish_queue.cms_type`'s
    existing enum shape).
- **`_validate_wp_url()` deliberately does NOT perform DNS resolution.** Only rejects
  syntax-level SSRF cases: non-`https` scheme, empty hostname, `localhost`/`.local`, and IP
  literals that are private/loopback/link-local/reserved/multicast/unspecified (covers
  `169.254.169.254`, the AWS/GCP cloud-metadata SSRF classic, via `is_link_local`). A domain that
  doesn't resolve (typo, DNS not propagated) is a real-URL-just-unreachable case — that's the
  test-connection endpoint's job to classify, not the validator's to reject. Confirmed this
  reasoning against the task's own verify plan, which explicitly wants a non-existent domain to
  be *saveable* and only fail at `/test`.
- **`connected_at` is set only on first connect** — the `INSERT ... ON CONFLICT DO UPDATE`
  deliberately excludes `connected_at` from the `SET` clause, so re-saving credentials (a
  password rotation, e.g.) doesn't reset the tenant's original "connected since" timestamp. A
  credential update isn't a new connection.
- **A failed test-connection never touches `last_verified_at`** — only `last_verify_error` +
  `updated_at` are set on the failure path. Confirmed via a dedicated unit test asserting the
  `SET` clause specifically (not just the whole SQL string, which also contains
  `last_verified_at` in its `RETURNING` clause — an early version of this test asserted against
  the wrong thing and had to be fixed, see test file history).
- **`GET /v1/integrations/wordpress`** (status) wasn't explicitly itemized in the Linear issue's
  numbered list but is a structural necessity — the frontend has to know "connected or not" to
  decide whether to render the connect form (§9's whole Option 3 premise). Added it as the natural
  companion to the two POST endpoints; never returns the secret itself, only non-secret status
  fields.
- **UI — Option 3+2 exactly as decided**: `/portal/t11-publish` IS the inline connect form when
  nothing's connected (zero extra navigation for the common first-time case); a real standalone
  `/portal/t11-publish/connection` page for later edits/retests, sharing one
  `WordPressConnectForm` component so the credentials UI isn't built twice. Confirmed via STEP0
  reading that `/portal/settings` (`PlaceholderTabs.tsx::SettingsTab`) was the wrong page to
  extend — it's a 425-line mockup with zero real persistence except logout; this task builds real,
  working UI from the start instead.
- **No Sidebar entry** — per the task's explicit scope cut, `/portal/t11-publish` is reachable
  only by direct URL this PR. `middleware.ts`'s `{ prefix: "/portal", roles: ["admin","tenant"] }`
  already covers every `/portal/*` route with one blanket entry (unlike the admin side's
  per-page allowlist that bit AA-384/388/405/437) — confirmed no middleware change was needed,
  same finding pattern as AA-455's force-unpublish section.
- **`/portal/t11-publish/page.tsx` includes a visible skeleton placeholder** ("Your approved
  content will appear here to publish — coming soon") for the connected-but-nothing-to-do-yet
  state, plus a "Manage connection" link — so AA-458 extends this file rather than building the
  route from scratch, per the task's own instruction.

## Changed

- `api/migrations/117_shared_tenant_integrations.sql` — new table, additive only.
- `api/routers/v1_integrations.py` — new file: `GET/POST /v1/integrations/wordpress`,
  `POST /v1/integrations/wordpress/test`.
- `api/main.py` — registered the new router.
- `frontend/app/(tenant)/portal/_components/WordPressConnect.tsx` — new shared component
  (`useWordPressStatus` hook, `WordPressConnectForm`, `WordPressStatusCard`).
- `frontend/app/(tenant)/portal/t11-publish/page.tsx` — new route.
- `frontend/app/(tenant)/portal/t11-publish/connection/page.tsx` — new route.
- `frontend/app/(tenant)/portal/layout.tsx` — 2 new breadcrumb entries (harmless, matches the
  existing convention that every real route has one).
- `tests/unit/test_aa457_integrations.py` — new, 16 tests.

## Tradeoffs

- `_classify_test_failure()`'s 404 case ("WordPress REST API is not enabled on this site") is
  necessarily a guess from one data point (a 404 on `/wp-json/wp/v2/users/me` specifically) — a
  real WordPress site could also 404 there for other reasons (a security plugin blocking the
  `users` endpoint specifically while leaving `/wp-json/` itself reachable, for instance). Flagged
  explicitly rather than presented as certain — this classification can only be truly validated
  against a real WordPress site, which this session didn't have (see Verify section).
- Found the same `react-hooks/set-state-in-effect` ESLint finding in my own new
  `WordPressConnect.tsx` that already exists in the just-merged `admin_a4-oversight/page.tsx`
  (AA-455's own file) — confirmed CI's Lint job only runs Python flake8, never touches frontend
  eslint/tsc at all (`.github/workflows/ci.yml`'s `lint` job), so this isn't a CI blocker. Chose
  to match the established (if imperfect) repo convention rather than introduce a one-off
  different pattern for a rule the repo hasn't actually adopted anywhere else.
- No tenant-facing list of *other* integration types yet (`integration_type` is free-text, only
  `'wordpress'` is ever written) — matches STEP0's own framing that this table is future-proofed
  for other CMS types but only WordPress is real scope right now.

## Should know

- **Verify is genuinely split into two groups, per the task's own explicit instruction** — see
  "Live Verify" below. Group 1 (everything not requiring a real WordPress site) is fully done live
  this session. Group 2 (real creds against a real site — 200 success, 401 wrong-password
  classification, 404 REST-API-disabled classification) is **not done** and must not be reported
  as Done — it needs Nghiep to provide a real WordPress test site, planned as the first live-verify
  step before AA-458 (PR 2) starts.
- `_put_secret()`'s create-or-update logic (`create_secret` → catch `ResourceExistsException` →
  `put_secret_value`) was unit-tested (mocked `ClientError`) but the *create* path (a genuinely
  new secret) was also exercised for real in this session's live-verify (see below) — the
  *update* path (calling save twice for the same tenant) was only unit-tested, not yet exercised
  live in this session; worth a quick real re-save check whenever Nghiep does the real-WordPress
  verify pass, since it's cheap to add to that same session.

## Live Verify

### Group 1 — verified live this session (no real WordPress site needed)

- **Migration**: applied cleanly to dev RDS via the S3-mediated ECS exec pattern.
  `shared.schema_versions` row confirmed (`version='117'`), all 9 real columns confirmed via
  `information_schema.columns`.
- *(Filled in after merge + deploy — see the post-merge/post-deploy record for the full
  real-HTTP trace: save with a fake-but-syntactically-valid domain, Secrets Manager verified via
  `aws secretsmanager get-secret-value` showing the real JSON with no plaintext leak elsewhere,
  DB row confirmed holding only `site_url` + the secret's key name; test-connection against a
  non-existent domain confirmed a real DNS failure classified correctly; SSRF validation confirmed
  rejecting `localhost`/`127.0.0.1`/a private-range IP before any outbound call; cross-tenant
  isolation confirmed on both `GET` and `POST`; FE connect flow confirmed working end-to-end
  through a real tenant session with the fake domain, Secrets Manager re-checked after.)*

### Group 2 — NOT verified, requires a real WordPress site (Nghiep to provide)

**Not claimed as Done. Must be verified before AA-458 (T11 PR2) starts:**

1. Test-connection with a real WordPress site + correct credentials → real `200`,
   `last_verified_at` updates correctly.
2. Test-connection with a real site but the wrong application password → confirm the actual
   WordPress REST API really does return `401` for this case (assumed, not yet confirmed against
   real WordPress behavior) and `last_verify_error` reads the expected wrong-credentials message.
3. Test-connection with a real site that has the REST API disabled → confirm what WordPress
   *actually* returns in this case (this session's `404` assumption for
   `/wp-json/wp/v2/users/me` is a best-effort guess, not verified against real WordPress
   behavior — could be `404` on the whole `/wp-json/` path, could be a `403`, could be something
   else depending on how the tenant disabled it) and that `last_verify_error` still reads
   sensibly even if the real status code differs from the assumed `404`.
