# AA-CIS-App Handoff — Session 56
Updated: 2026-06-11

## Status
- Branch: develop @ 03e6322 | PR #33 (develop -> main) OPEN, awaiting human merge
- ECS: api (latest dev image deployed via Deploy Dev #27348492360) — RUNNING, STOP after session
- RDS: aa-cis-dev-db RUNNING — STOP after session
- Deploy Dev (develop): SUCCESS ✅ | CI on develop: SUCCESS ✅

## Completed This Session

### AA-181 — ACP tenant-auth: collapse to single-header (X-API-Key/X-Admin-Secret) ✅

**feature/aa-181-single-header-tenant-auth → develop (merged) → PR #33 (develop->main, open)**

- New shared dependency `verify_tenant_api_key` in `api/routers/auth.py`:
  multi-credential — `X-API-Key` (raw `cis_...`, sha256 vs `shared.tenants.api_key_hash`)
  OR `X-Admin-Secret` (AA internal sentinel). 401 if neither valid.
  Returns `reviewer_type` (`aa_internal`|`tenant_self`) for gate audit (AA-186 prep).
- 6 routers migrated off JWT/HTTPBearer + old admin-secret-only deps via aliased imports
  (zero call-site changes): `v1_acp.py`, `v1_s1.py`, `services/acp/s2/router.py`,
  `v1_acp_gate.py`, `v1_s4_blog.py`, `v1_s4_social.py`.
- `/auth/tenant-login` kept, marked `deprecated=True`.
- `v1_acp_gate.py`: new `_audit_actor_type()` maps `reviewer_type` → existing
  `acp_shared.audit_actor_type` enum values for `audit_log` writes.
- Added OpenAPI security schemes `TenantApiKey`/`AdminSecret` (Swagger now documents both
  headers on all 6 routers).
- Out of scope (untouched, confirmed): `v1_s3.py`, `/v1/hitl/gate2`, `acp_health.py`.
- Full details: `docs/implementation-notes/AA-181.md`

**Tests: tests/unit/test_auth_tenant_api_key.py 5/5 green | flake8 (CI config) clean**

### CI/CD chain
- feature CI (9343df3): all green (Lint, Security Audit, Unit, Integration, Docker Build,
  Vercel Preview)
- develop CI (fedc078): all green | Deploy Dev (27348492360): SUCCESS ✅

### E2E verify (production ECS, https://api-cis.lumiguides.it.com)
- `GET /v1/acp/runs?limit=1` + `X-API-Key: cis_u1k...` → `200` (real run data) ✅
- No header → `401` | invalid key → `403` (APIGW authorizer)
- `POST /acp/s1/run` + valid `X-API-Key` → `422` (validation layer reached — auth passed)

## Unplanned: develop branch recreated
- `develop` was auto-deleted by GitHub after PR #32 (AA-174, develop->main) merged earlier
  today. Recreated `develop` from `origin/main` (superset of old develop) before merging
  AA-181 in — confirmed with user first. PR #33 opened develop->main.

## Open Issues (carried over)
- PR #33 (develop -> main) needs human merge -> triggers Deploy Prod
- OPENAI_API_KEY needs rotation
- 8 pre-existing test failures (test_s2_idempotency, test_s2_semaphore,
  test_h3_rule_extractor) — pre-existing, reconfirmed unrelated to AA-181 via git stash
- feature/aa-112-s2-async-postgres-saver: DO NOT merge
- feature/aa-143-canary: DO NOT merge
- feature/aa-141-run-health-dashboard: DO NOT merge
- Frontend `/acp/s1/*` calls (admin pipeline S1 page) use Bearer token against APIGW base
  URL with no `/acp` resource — looks pre-existing broken/dead, unrelated to AA-181, not
  investigated further

## Next
- Human: review + merge PR #33 (develop -> main) -> Deploy Prod
- AA-186: full reviewer_type audit work (builds on `_audit_actor_type()` mapping added here)

## Cost Checklist (MANUAL — do not auto-run)
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
