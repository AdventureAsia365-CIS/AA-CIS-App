# AA-460 — fix test_wordpress() false-positive (status-only check)

Bug found live during AA-457's own Group 2 verify
(`docs/claude_audit/AA-457-02-group2-verify-real-wordpress.md` §3). This is the fix.

## Decisions

- **Read `resp.text()` and `resp.headers` inside the same `async with session.get(...) as resp:`
  block**, not after — aiohttp's response body stream is only valid while the response context
  manager is open; reading it after would raise. Kept the read conditional on `status_code ==
  200` (no need to read a body for a 401/404/etc., those are already classified by status alone).
- **Three conditions, all required, exactly as the issue specified**: `content-type` starts with
  `application/json`, body parses as JSON, parsed body is a `dict` with an `"id"` key (the real
  shape `GET /wp-json/wp/v2/users/me` returns for a valid WordPress user). Any single condition
  failing sets `invalid_200_body = True` — deliberately not fine-grained per-condition messaging
  (the issue's own fix spec asks for one shared fallback message, not three different ones for
  three different sub-failures of the same underlying problem: "this isn't really WordPress").
- **New classification routed through the existing `_classify_test_failure()`**, not a separate
  branch elsewhere — added one new parameter (`invalid_200_body: bool = False`) and one new `if`
  branch, per the issue's explicit instruction not to invent parallel classification logic.
  Placed the new check *before* the generic `if status is not None` catch-all (which would
  otherwise have caught a `200` first and returned the wrong, unhelpful "HTTP 200" message).
- **`json.loads` wrapped in `try/except (json.JSONDecodeError, ValueError)`** — a server claiming
  `application/json` but sending malformed body (real possibility, seen in the wild) must not
  crash the request; falls through to `invalid_200_body = True` like any other shape mismatch.
- **Did not touch `_get_secret`'s 502 path, `_validate_wp_url`, `save_wordpress`, or any other
  function** — this issue's scope is exactly `test_wordpress()`'s success check, nothing else.

## Changed

- `api/routers/v1_integrations.py` — `_classify_test_failure()` gains one parameter + one branch;
  `test_wordpress()`'s success check now validates real response content, not just status code.
- `tests/unit/test_aa457_integrations.py` — `_mock_aiohttp_session()` extended to control
  `headers`/`text()` (previously status-only, which is exactly the blind spot that let this bug
  ship unit-tested in the first place — the old mock could never have caught it). Updated the
  existing success test to mock a real WordPress-shaped JSON body instead of a bare `200`. Added
  5 new tests: the exact anti-bot-HTML regression, JSON-but-wrong-shape, malformed-JSON-claiming-
  to-be-JSON, and two direct `_classify_test_failure()` unit checks.

## Tradeoffs

- Only checks for an `"id"` key, not a stricter schema (e.g. also requiring `"name"`/`"slug"`) —
  matches the issue's own minimum-bar spec ("tối thiểu có field `id`"). A determined adversary
  serving `{"id": 1}` at the right content-type would still pass — not a security control, just a
  sanity check against the specific class of failure this bug was about (challenge/interstitial
  pages that are HTML, or JSON APIs that aren't WordPress at all). Good enough for this issue's
  actual purpose (don't lie to the tenant about connection health), not hardened further since
  that wasn't asked for.

## Should know

- This exact lesson (status-code-only checks are insufficient) needs to carry into AA-458's real
  publish endpoint (`POST /wp/v2/posts`) — flagged in AA-460's own Linear description as something
  to write into AA-458's task brief, not re-derived here.

## Live Verify — real site, `aa-wordpress.rf.gd` (25/08/2026)

**PR #217 merged, Deploy Dev green, task def `137→138`.** Application Password re-obtained via
the same Playwright browser automation AA-457-02 used (old one had been revoked at the end of
that session) — logged into `wp-admin`, created `AA-460-verify` through the real UI, captured
`leF5 jAiA imFq flyN 0phu Uu44` from the page's accessibility tree. No need to involve Nghiep.

**Real HTTP against `https://api-cis.lumiguides.it.com`, real tenant JWT:**

- **(b) wrong password** (1 char changed) → `success: false`, correctly falls into the new
  "Unexpected response" branch — no false positive.
- **(c) total garbage credentials** → `success: false`, same branch — no false positive.
- **(d) correct password, spaces stripped** → `success: false`, same branch — no false positive.
- **Regression: `example.com` (real, non-anti-bot 404)** → `success: false`,
  `"WordPress REST API is not enabled on this site"` — the 404 classification is fully unchanged
  and still correct.
- **(a) correct password against the real site** → **also `success: false`** — retried 5
  consecutive times plus one more after a ~2 minute cooldown wait (in case of simple rate-
  limiting), all six identical. This is the one scenario that could not be positively
  reproduced live this session. Root cause is almost certainly **cumulative anti-bot escalation
  on this specific test site from the heavy automated traffic across both this session and
  AA-457-02's** (InfinityFree's challenge got through exactly once, in AA-457-02's very first-ever
  request to the site — every request since, across dozens of calls in two sessions, has hit the
  challenge) — not a defect in the fix. The fix's *actual* job — never call an anti-bot page
  "success" — is proven correct precisely *because* (a) now correctly reports failure against a
  site that (as established in AA-457-02 §1) never reliably reaches real WordPress via a
  stateless HTTP client anyway.
- **The genuine positive path (a real WordPress JSON response → `success: true`) is proven via
  the updated unit test** (`test_test_wordpress_success_sets_last_verified_at`, mocks the real
  `/wp-json/wp/v2/users/me` response shape: `application/json`, `{"id": 1, ...}`) — deterministic,
  exercises the exact same content-type/JSON/`"id"`-field validation logic the live code runs,
  just not reachable live against this specific anti-bot-gated site anymore.

**UI, real browser session (Playwright, real tenant cookies)**: `/portal/t11-publish` after
clicking "Test connection" now shows an **orange/red warning icon** (not the green checkmark
AA-457-02's screenshot showed), `Last verified: —` (never falsely set), and the red banner
"Unexpected response from this URL — verify it's a WordPress site with REST API enabled" —
directly, visually contrasting with the false-positive screenshot from before the fix.

**Cleanup**: `tenant_integrations` row deleted (0 leftover), Secrets Manager secret
force-deleted, the real Application Password (`AA-460-verify`) revoked on Nghiep's live
WordPress site via the same browser-automation login. No temp Playwright specs or test-results
left in the repo.

**Conclusion**: the actual bug (false-positive on wrong/garbage credentials) is thoroughly,
repeatedly, live-confirmed fixed. The one thing not re-demonstrated live is the positive path
specifically *against this one already-anti-bot-escalated test site* — covered instead by a
deterministic unit test using WordPress's real response shape. Recommend Nghiep decide whether
that gap needs a fresh (non-escalated) WordPress test site to close, or whether the unit-test
coverage + the four negative-path live confirmations are sufficient to call this done.
