# CLAUDE.md — AA-CIS-App

## Project Context
AA-CIS (Content Intelligence System) — AI-powered B2B tour content automation platform.
Part of AA_Ecosys program. Internal admin tool for Adventure Asia content team.

## Stack
- **Backend**: FastAPI (Python 3.12), PostgreSQL 15, LangGraph, AWS Bedrock
- **Frontend**: Next.js 14 (TypeScript), Tailwind CSS, Vercel
- **Infra**: AWS ECS Fargate Spot, RDS, ElastiCache Redis, Step Functions
- **Account**: 867490540162 | Region: us-west-1 | Profile: pqnghiep-admin

## Git Workflow (NON-NEGOTIABLE)
```
feature/aa-XX-desc → develop → CI green → Deploy Dev green → main → Deploy Prod
```
- NEVER merge directly to main
- Always create feature branch from develop
- Branch naming: feature/aa-XX-short-desc | fix/aa-XX-desc | chore/desc

## Code Patterns

### Python
- Type hints everywhere, async-first (FastAPI patterns)
- Schema-qualify all DB queries: `silver_aa_internal.raw_tours` not `raw_tours`
- Bedrock for LLM calls (not Anthropic SDK directly)
- structlog for logging

### Database
- RDS PostgreSQL 15 in private subnet — access via ECS Exec + python3
- S3-mediated ECS Exec pattern for DB queries (see aa-cis-schema skill)
- Always verify column existence before querying (schema changes frequently)
- Migration files: `api/migrations/NNN_description.sql`
- Current latest migration: 067 (social_content.angles_json)

### Testing
- pytest + AsyncMock for all new code
- Tests in `tests/` (unit) and `tests/unit/` (existing)
- Minimum: 4 tests per new module
- Mock all external calls (DB, LLM, S3)

### AWS CLI (WSL2-safe)
- NEVER multi-line with backslash — hangs WSL2
- Always single-line commands
- Always include --profile and --region

## AWS Resources
- ECS: aa-cis-dev-cluster / aa-cis-dev-api
- RDS: aa-cis-dev-db (PostgreSQL 15)
- NAT Instance: i-04ebd090e97184f45 (t4g.nano) — start/stop per session
- S3 Scripts: aa-cis-bronze-867490540162/scripts/

## Session Aliases (~/.zshrc)
```bash
cis-start  # start NAT Instance + RDS + ECS
cis-stop   # stop ECS + RDS + NAT Instance
cis-status # check NAT instance state
```

## Current State (16/06/2026)
- Branch: develop (main = production); develop @ c4dacb3, main @ 883a3cd
- ECS task def: api:304 (digest verified == ECR :latest sha256:a65dfcd…230b67)
- Latest migrations: 065 (acp_stage_checkpoints), 066 (quality_score), 067 (angles_json), 068 (s1_tour_ids_run_context)
- Wave 4 complete: AA-145 S4.2 v2 shipped
- AA-198 [AA-193·F1] SHIPPED: brand_identity_id resolver (id → named-active → explicit default),
  GET /admin/brand-rules, forbidden_words prompt inject, s1 brand-picker keyed on id.
- AA-197 [AA-193·F2] SHIPPED: DataForSEO rebuild — seed_builder (normalize country, no double-tours),
  buyer-market location from tenant_seo_config.target_market via TenantConfigService (was unwired),
  3 DFS calls/tour + real keywords_for_keywords ideas (volume/competition/cpc), ideas→top_keywords fallback.
- NOTE: "Deploy Prod" GitHub workflow is a STUB (placeholder, no-op). Real ECS deploy = "Deploy Dev" on develop merge.

## Do NOT
- Hardcode secrets (use Secrets Manager)
- SSH into instances (use SSM)
- Use eth0 interface name (AL2023 ARM64 uses ens5)
- Merge to main without CI green
- Leave AWS resources running after session
