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

## Live Verify — real site, `aa-wordpress.rf.gd`

See "Live Verify" section appended after running against the real site (Application Password
re-obtained via the same Playwright automation AA-457-02 used — no need to involve Nghiep).
