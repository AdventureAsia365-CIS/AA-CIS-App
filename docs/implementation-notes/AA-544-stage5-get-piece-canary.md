# AA-544 Stage 5 — second pool-switch canary: `GET /v1/content-writing/pieces/{piece_id}`

Part of AA-544's approved 7-stage rollout. Stage 5 = expand the pool-switch canary to another
low-risk route, each independently revertible via its own flag (per the plan's own wording:
"mo rong dan tung route, moi route revert rieng qua flag").

## Decisions

- **Route chosen: `GET /v1/content-writing/pieces/{piece_id}`** (`fetch_piece()`,
  `services/acp_content_writing/service.py`). Checked every other GET route in
  `v1_content_writing.py` first: `GET .../reviews` and `GET .../requests/{id}/review` both JOIN
  `acp_contract.tour_atoms`, a schema `aa_app_user` has **no GRANT on at all** (not even schema
  `USAGE` — `acp_contract` was deliberately left out of Stage 0's grant list as admin-only) — those
  would fail hard (permission denied) if switched today, not silently misbehave; ruled out.
  `GET .../requests/{id}/latest-piece` is safe but touches 2 tables across 2 sequential queries;
  `fetch_piece()` is simpler still — one table, one query, no JOIN at all, and it's the real poll
  endpoint the frontend calls repeatedly after every `POST .../write` until the piece resolves —
  higher real traffic than Stage 1's canary.
- **Generalized `acquire_scoped_conn()` to take a `flag_key` per route** instead of Stage 1's
  hardcoded single flag. Named constants added to `api/core/aa544_tenant_pool.py`
  (`STAGE1_PUBLISH_PENDING_FLAG`, `STAGE5_GET_PIECE_FLAG`) so each route's rollout is
  independently revertible, matching the original plan's own Stage 5 wording. Stage 1's route
  updated to pass its flag explicitly; no behavior change for it.
- **`fetch_piece()` takes an optional `request` param** (default `None`) rather than requiring
  every caller to pass a `Request` — the router passes it; a handful of unit tests and any other
  direct caller that only has a bare `pool` keep working unchanged (falls through to the
  pre-Stage-5 `pool.acquire()` path). Avoids threading a FastAPI `Request` object into a
  service-layer function's mandatory signature for what is, for most callers, irrelevant.

## Changed

- `api/core/aa544_tenant_pool.py` — `acquire_scoped_conn(request, tenant_id, flag_key)` now
  takes `flag_key` explicitly; `_flag_enabled()` replaces the old single-flag
  `stage1_flag_enabled()`. Module docstring updated to track both live canary routes.
- `api/routers/v1_publish.py` — passes `STAGE1_PUBLISH_PENDING_FLAG` explicitly (no behavior
  change).
- `services/acp_content_writing/service.py::fetch_piece()` — optional `request` param; when
  given and the Stage 5 flag is on, runs through `acquire_scoped_conn()`. Query text unchanged
  (extracted to `_FETCH_PIECE_QUERY` for reuse across both code paths).
- `api/routers/v1_content_writing.py::get_piece()` — passes `request=request` through.

## Tradeoffs

- `GET .../requests/{id}/reviews` and `.../review` (the other 2 GET routes in this file) stay
  admin-pool for now — not because they're unsafe in principle, but because moving them needs a
  new GRANT on `acp_contract.tour_atoms` first (out of Stage 5's scope: "pick one route"). Noted
  here so a future stage doesn't have to re-derive it.

## Should know

- **Live-verify, real RDS dev, before any HTTP-level test** (independent of deployed app code):
  300 concurrent coroutines, pool `max_size=2` (forces physical connection reuse), mixing
  `wanderlux-travel` (real, 15 content_piece rows of which 3 sampled for this test) probing both
  its own real piece_ids and a fake one, `exploreasia-co` (real, 0 rows) and 8 synthetic tenant
  IDs always probing wanderlux's real piece_ids (the actual cross-tenant leak shape) or a fake
  one. Result: **0 errors** — wanderlux saw `found=true` only for its own real pieces and
  `found=false` for the fake one; every other tenant saw `found=false` unconditionally, even
  when directly probing a real wanderlux piece_id. GUC readback always matched the tenant that
  set it.
- Default state after merge: both flags unset → both canary routes fall back to the unchanged
  admin pool. Turning Stage 5's flag on is a separate, deliberate step, not part of this PR.
- **Full end-to-end HTTP verify — done post-deploy (10/09/2026)**: PR #369 merged (`209db24`),
  Deploy Dev green, ECS rollout COMPLETED (task def `:270`). Real flow via ECS-internal
  `localhost:8000`: generated a fresh API key for `wanderlux-travel`, real `tenant-login`, then
  called `GET /v1/content-writing/pieces/{real piece_id}` 3 times against the real deployed
  route: flag OFF (`status=held`) → flag ON (`status=held`) → flag deleted (`status=held`) —
  response bodies byte-identical across all 3. Independently confirmed via CloudWatch
  (`aa544_stage5_fetch_piece`) that `used_tenant_pool` flipped `False → True → False` across
  those 3 calls. Both Stage 1 and Stage 5 flags confirmed unset after the test — system back in
  its default-off state for every request.
