
---

## Session 39 — 29/05/2026

### Shipped
- AA-135: brand_standards.py (AA_BRAND_IDENTITY_PROMPT + AA_COWORK_STRUCTURE_PROMPT)
- AA-133: brand_audit_node.py — GPT-4.1 LLM-as-Judge, 8 pre-checks, wired into graph
- AA-134: flag_fix_node.py — targeted fix, fix_pass columns, /admin/export-audit
- AA-132: write_lessons_log() — auto write-back vào shared.pipeline_lessons
- B0 bugs: SEO schema mismatch (B1), seo_data normalize (B2), seo_mode propagation (B3)
- UI: BrandAuditBadge, Audit column, Version Compare brand panel, Export Audit CSV button
- Migration 050: brand_audit_* columns on quality_scores + fix_pass_* on generated_content

### Graph flow (updated)
generate → validate → brand_audit (GPT-4.1) → flag_fix → END
brand_audit chỉ chạy trên "done" path (score ≥ 7.0)

### Known issue
- API Gateway 29s timeout → run-tour 504 via HTTPS. Use ECS Exec trực tiếp. Fix P4-S6.
- OPENAI_API_KEY cần rotate (lộ trong session 39)

### State
- ECS task def: api:246 | Deploy Prod #53 | commit 388bf56
- AWS: STOPPED (ECS desired=0, RDS stopped)
- .flake8: max-line-length=99 added
