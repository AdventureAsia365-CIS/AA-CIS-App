# AA-443 — portal layout.tsx reading httpOnly cookie (gap left by AA-427)

Branch: `fix/aa-443-layout-httponly-cookie` → PR #195 → squash-merged to `main` (`0ea70dd`) →
`Deploy Dev` green → verified live.

## Decisions
- Reused AA-427's exact fix pattern (`fetch("/api/tenant/me")` instead of reading httpOnly
  cookies via `document.cookie`) rather than inventing a different approach — 3 other files in
  PR #184 already use this pattern, keeping the codebase consistent.
- Bundled 2 unrelated stale-file deletions (`AA45_S3_SPEC.md`, a Windows `Zone.Identifier`
  artifact) into this same small PR rather than a separate one, per Nghiep's explicit call —
  harmless cleanup, not worth a second PR/CI cycle.
- Did NOT touch `services/acp_shared/grounding.py` — a different, unrelated fix that was sitting
  in the same uncommitted stash this was discovered in. Explicitly dropped per Nghiep's decision
  (AA-349 pending a broader redesign of that module; shipping the narrower patch first means
  revisiting it twice). See `docs/implementation-notes/AA-347-grounding-ordinal-patch-not-shipped.md`
  (untracked, kept as reference for that future work).

## Changed
- `frontend/app/(tenant)/portal/layout.tsx`: `getCookie("cis_tenant_name")` /
  `getCookie("cis_tenant_plan")` → `fetch("/api/tenant/me")`.
- Deleted `AA45_S3_SPEC.md`, `docs/CIS_Runbook_v1.md:Zone.Identifier`.

## Tradeoffs
- No headless browser available in this environment, so the `useEffect` actually updating the
  rendered DOM (post-mount, in a real browser) was not directly observed. Verification instead
  targeted the data source (`/api/tenant/me`) and, post-deploy, the compiled client bundle itself
  — see Verify below. Confidence is high given this is a 3-line, mechanical copy of an
  already-proven-working pattern, but flagging the gap in rigor honestly rather than overstating it.

## Should know
- This file (`layout.tsx`) is the shared portal shell (AA-430 route migration) — a different file
  from `portal/page.tsx`, which AA-427 correctly fixed. Two files independently read the same 2
  cookie names; AA-427 only caught one.
- Origin story: found while investigating an unrelated uncommitted stash during AA-441 — see that
  session's report for the full stash investigation (not repeated here).

## Verify

**Pre-merge:**
- `tsc --noEmit` (whole frontend project): 0 errors.
- Local dev server (`next dev`, `API_URL` pointed at the real deployed backend) → `GET
  /api/tenant/me` with a real tenant JWT (`test-n1-flow`) → `200
  {"tenant_id":"6fbaf284-...","tenant_name":"TEST-N1-flow","plan_tier":"business"}` — the exact
  data this fix's `fetch()` call now consumes, confirmed correct.

**Post-merge, post-deploy (live production):**
- `Deploy Dev` workflow: Vercel + ECR build + Lambda + ECS Dev all `success`.
- `GET https://aa-cis.lumiguides.it.com/api/tenant/me` (real production frontend domain) with the
  same real tenant JWT → same correct `200` response, live.
- Downloaded the actual deployed JS chunks referenced by `https://aa-cis.lumiguides.it.com/portal/
  dashboard` and grepped them directly: the literal string `cis_tenant_name` (used only by the old
  `getCookie()` call) is **absent** from every chunk; `api/tenant/me` **is present** — direct
  confirmation the compiled, deployed client bundle contains the new code, not the old one.
- ECS `aa-cis-dev-api`: steady state, 1/1 running, single `PRIMARY` deployment (no crash-loop from
  this deploy cycle, even though this PR touched no backend code).
