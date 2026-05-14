# CIS Session 11 Handoff — 14/05/2026

## Status: Phase 4 COMPLETE ✅

## AWS State
- ECS aa-cis-dev-api: desired=0, running=0 (STOPPED)
- RDS aa-cis-dev-db: stopping → will be stopped
- API Gateway: owq9as3wjl (ALWAYS ON — no cost when idle)
- Lambda Authorizer: aa-cis-dev-authorizer (ALWAYS ON — no cost when idle)

## Last Deploy
- ECS task def: api:137
- CI #218 ✅ | Deploy Dev #130 ✅
- Vercel Production: 4iiN9RaQ2 (commit 85ed50d)

## Completed This Session
- AA-57: Tenant detail bugs (quality_score, pipeline→activity tab, aa_internal tours)
- AA-23: Remove Langfuse (~$8/mo saved)
- AA-22: SF fallback router (threshold=15) + HITL IAM fix
- AA-13: API Gateway REST + Lambda Authorizer + 4 usage plans + custom domain
- AA-60: Dashboard all-tenant metrics + all X-API-Key routing fixes

## API Gateway Routing (IMPORTANT)
All server-side Next.js routes calling /v1/* MUST either:
  a) Use /api/tenant/ proxy (handles X-API-Key automatically)
  b) Add header: X-API-Key: INTERNAL_API_KEY

Public routes (no auth): /health, /auth/*, /docs, /openapi.json
Admin routes (JWT only): /admin/*
Content routes (JWT only): /content/*
B2B routes (X-API-Key required): /v1/*

## Next Session
1. AA-11: Phase 3 Report DOCX → Ms. Thu (Claude Chat, no AWS needed)
2. Regenerate aa_internal API key: POST /admin/tenants/{id}/rotate-key
3. Disable WAF after verifying API GW rate limiting stable
4. Consider Phase 5: Webhook notifications, B2B self-signup

## Start Next Session
aws rds start-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 1 --profile pqnghiep-admin --region us-west-1
