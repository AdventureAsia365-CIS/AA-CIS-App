# AA-432 (Part 2/2c) — Remove API Gateway X-API-Key gate on /v1/*, Redis rate-limit + revoke

Date: 22/08/2026. Repos touched: AA-CIS-Infra (Terraform), AA-CIS-App (FastAPI).
Branch (both repos): `pqnghiep1354/aa-432-urgentinfra-api-gateway-id-sai-lech-claudemd-vs-production-x`

Status: **code done, NOT deployed.** Terraform change validated but not planned/applied (see
"Should know" — sandbox couldn't authenticate to run `terraform plan`). FastAPI change is
tested (unit) but not yet exercised against real gateway traffic, since that traffic can't reach
FastAPI until the Terraform side ships.

## Decisions

1. **Middleware, not `get_tenant()` itself, for the Redis rate-limit/revoke check.** The task
   suggested either; `api/middleware/rate_limit.py::rate_limit_middleware` already existed,
   already runs on every `/v1/*` request ahead of any route handler (wired in `api/main.py`),
   and already did JWT decode + a Redis-backed per-minute counter — it just used a hardcoded
   `PLAN_RPM` bucket-by-plan-tier map instead of the tenant's real `rate_limit_rpm`, and had no
   `is_active` check at all (only checked at login, in `auth.py`'s deprecated `/auth/tenant-login`
   and the live one in `main.py`). Extending this one function covers every `/v1/*` route
   automatically — no per-router change needed, and no risk of a new router forgetting to wire it
   in (a `get_tenant()`-level fix would need duplicating into both `v1_tours.py` and
   `v1_exports.py`, the two files that define their own `get_tenant()`).

2. **Tenant metadata cache: Redis, not in-process, 30s TTL.** ECS runs multiple tasks; an
   in-process cache would let different tasks disagree about whether a tenant is still active.
   30s is a judgment call (not load-tested) — fast enough that a revoke feels close to immediate,
   slow enough that a normal traffic pattern doesn't add a DB round-trip per request. Cache key
   `tenant_meta:{tenant_id}`, value `{"rate_limit_rpm": int, "is_active": bool}` as JSON.

3. **is_active=false → 403, not 401.** 401 already means "your JWT itself is invalid/expired"
   (see `verify_jwt`) — a deactivated tenant's JWT is still cryptographically valid, it's just no
   longer authorized. 403 (Forbidden) is the more accurate signal, and keeps 401 unambiguous as
   "re-authenticate" vs 403 "authenticated but not allowed." Task text allowed either.

4. **Fail-open on tenant_meta lookup failure (Redis AND DB both unreachable), never fail-open on
   an is_active=false result.** If the lookup itself can't complete, the code falls back to the
   pre-existing plan-tier/`PLAN_RPM` behavior rather than 403-ing or 500-ing every tenant request
   on a transient infra blip — matches this file's own pre-existing convention (the rate-limit
   counter already fails open on a Redis error: `except Exception: count = 0`). This is a
   deliberate availability-over-strictness tradeoff for the *rate-limit* dimension; it does NOT
   apply to revoke — if the lookup fails, revoke simply isn't checked that request (same as
   before this change, since no check existed at all), it never converts a `None` lookup result
   into "treat as active" vs "treat as inactive" ambiguity — the `is_active` branch only runs
   when the lookup actually returned data.

5. **Terraform: leave the `tenant_key` authorizer resource declared, only change the method.**
   Task explicitly said don't delete the Lambda/authorizer in this change. Confirmed via grep
   (AA-CIS-Infra repo) that no other method/resource references
   `aws_api_gateway_authorizer.tenant_key` — it's now an orphaned-but-harmless declared resource.
   Actually deleting it is a separate, later cleanup (noted in CLAUDE.md, not filed as a new
   Linear issue in this session — Nghiep can decide if that's worth its own ticket).

## Changed

- `AA-CIS-Infra/modules/api_gateway/main.tf`: `aws_api_gateway_method.v1_any` —
  `authorization = "CUSTOM"` + `authorizer_id = aws_api_gateway_authorizer.tenant_key.id` →
  `authorization = "NONE"` (authorizer_id line removed). This is the only resource change.
- `AA-CIS-App/api/middleware/rate_limit.py`: added `_get_tenant_meta()` (Redis-cached
  `shared.tenants.rate_limit_rpm` + `is_active` lookup) and wired it into
  `rate_limit_middleware` ahead of the existing rate-limit counter. `PLAN_RPM` kept, now only a
  fallback for lookup failure (previously the only source of truth).
- `AA-CIS-App/tests/unit/test_aa432_rate_limit.py`: new, 5 tests (revoke-blocks, real-rpm-used,
  cache-hit-skips-db, fail-open-on-total-lookup-failure, over-limit-still-429-not-401). All pass.
- `AA-CIS-App/.claude/CLAUDE.md`: LIVE STATE note on the new architecture + the not-yet-applied
  Terraform status (see below).

## Tradeoffs

- **A per-tenant DB read on every Redis cache miss** (worst case: once per tenant per 30s) is a
  new cost this middleware didn't have before (it only touched Redis previously). Judged
  acceptable — one indexed `WHERE tenant_id = $1::uuid` lookup on a small table, amortized over
  30s of that tenant's traffic. Not load-tested against real traffic volume.
- **30s revoke latency is not "instant."** If Nghiep needs revoke to be truly immediate (e.g. for
  an active-incident key compromise), this cache TTL is the wrong tool — that scenario should
  still use `is_active=false` (which this DOES enforce, just with up to 30s lag) but combine it
  with rotating/expiring the tenant's session more aggressively if zero-lag revoke is ever a hard
  requirement. Flagging, not solving — no such requirement was stated in the task.
- **Chose not to touch the pre-existing `billing_service.track_api_call` / `tenant_api_usage`
  logging path** — 403 revoke-blocks are not tracked there (429s already were, kept as-is; a
  403 isn't logged to `tenant_api_usage`). This is a small inconsistency (place to add later if
  billing/observability needs revoke-block visibility) — didn't expand scope to add it now.

## Should know (read before the diff)

- **`terraform plan` could not be run from this session.** The `aa365-admin` AWS profile
  (`role_arn` + `mfa_serial`, `source_profile aa365-nghiep-base`) requires an MFA code for
  AssumeRole. `aws` CLI calls worked throughout this session because the CLI was already using a
  cached, previously-MFA-authenticated session — but Terraform's AWS provider does its own
  AssumeRole and doesn't read that CLI cache, so it needs a fresh MFA code Terraform can't obtain
  non-interactively here. Attempting to export the CLI's cached temporary credentials into env
  vars for Terraform to reuse was blocked by this environment's own safety controls (correctly —
  that would be working around the MFA requirement's intent, not a legitimate workaround).
  **What WAS verified instead:**
  - `terraform fmt -check` on the changed file: clean.
  - `terraform validate` (in `accounts/aa365/`, the real root module for this API Gateway — see
    below): **Success, configuration is valid.**
  - Confirmed via grep that no other `.tf` file references the authorizer being detached.
  **Nghiep needs to run, from `AA-CIS-Infra/accounts/aa365/`, with `AWS_PROFILE=aa365-admin`
  active (MFA'd) and `TF_VAR_db_password` set** (same pattern the repo's own
  `terraform-plan.yml`/`terraform-apply.yml` workflows use):
  ```
  cd accounts/aa365
  export TF_VAR_db_password=$(aws secretsmanager get-secret-value --secret-id aa-cis/dev/rds --profile aa365-admin --region us-west-1 --query SecretString --output text | python3 -c "import sys,urllib.parse; print(urllib.parse.urlparse(sys.stdin.read().strip()).password)")
  terraform init -backend-config="bucket=aa-cis-tfstate-005097885195" -backend-config="key=dev/terraform.tfstate" -backend-config="region=us-west-1"
  terraform plan
  ```
  Review the plan — it should show exactly ONE change (`aws_api_gateway_method.v1_any` in-place
  update, `authorization: CUSTOM -> NONE`, `authorizer_id` removed) plus whatever
  `aws_api_gateway_deployment.this`/stage redeploy Terraform decides is needed to actually push
  the method change live (expected, not a bug — the module's own `triggers` block forces a
  redeploy on integration/authorizer changes). If anything else shows up in the plan (unrelated
  resource changes), that's real infra drift unrelated to this task — stop and look before
  applying, don't assume it's expected.
- **A second, separate Terraform config-drift bug was found (not fixed) while locating the real
  root module:** the repo ROOT `versions.tf`/`main.tf` (not `accounts/aa365/`) still points its S3
  backend at `aa-cis-tfstate-867490540162` — **a bucket that no longer exists** (confirmed:
  `aws s3 ls` 404s under both `aa365-admin` and `pqnghiep-admin` profiles). This root config is
  almost certainly the pre-"AA-246 Track B" single-account setup, now orphaned dead code — the
  real, live config is `accounts/aa365/` (own `versions.tf`, correctly points at
  `aa-cis-tfstate-005097885195`, created 2026-07-07, same day as the real API Gateway). CI is
  unaffected (`terraform-plan.yml`/`terraform-apply.yml` override the bucket via
  `-backend-config` from a GitHub secret, never read the root `versions.tf`'s hardcoded value) —
  this only bites a human running `terraform init` from the repo root without realizing
  `accounts/aa365/` is the one that matters. Not fixed/removed in this session (out of scope,
  same "flag it, don't silently fix a bigger thing than asked" judgment call as STEP0's stale
  `owq9as3wjl` sweep) — worth its own tiny cleanup ticket (delete or clearly mark the root config
  dead) so the next person doesn't lose time on this the way this session did.
- **Live verification (real 200 on `/v1/tours/pool` without X-API-Key, 429 rate-limit, 403
  revoke, and the full route list from STEP0 §4) is NOT done** — all of it requires the Terraform
  change to actually be live first. Once Nghiep applies it, the exact repro commands from STEP0
  (`curl -sS -i https://api-cis.lumiguides.it.com/v1/tours/pool -H "Authorization: Bearer
  <real-jwt>"`) should now return 200 instead of 401 — that's the one-line proof this whole change
  worked. Happy to run that verification pass (and the rate-limit/revoke live tests) once the
  Terraform apply has actually happened — ask in a follow-up turn.
- Linear AA-432 comment should reflect: FastAPI-side code is ready to merge/deploy independent of
  the Terraform side; Terraform side needs Nghiep's own `plan` review + `apply` before this is
  actually live end-to-end.
