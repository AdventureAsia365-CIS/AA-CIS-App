# DELETED: deploy-prod.yml

**Date removed:** 31/07/2026, decision by Nghiep (S131)

## Reason

Solo-operator mode. This workflow was always a no-op stub — it never authenticated to AWS
and never deployed anything (confirmed by reading the file, the actual run logs, and
Terraform state during S131 STEP 0 investigation: only one ECS cluster/service has ever
existed, `aa-cis-dev-cluster`, tracked by a single `dev/terraform.tfstate`; `envs/prod/` in
AA-CIS-Infra is empty, never applied). Removing it to reduce noise in the Actions tab —
every merge to `main` was showing a "Deploy Prod" run that did nothing but `echo`.

## Original content (verbatim)

```yaml
name: Deploy Prod

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  id-token: write
  contents: read

jobs:
  deploy-prod:
    name: Deploy to Production (stub)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Placeholder
        run: echo "Prod deploy not yet configured — implement when prod environment is ready"
```

## Rollback instructions

When a team forms and a real prod environment is provisioned, restore `deploy-prod.yml` from
git history (`git log --all --full-history -- .github/workflows/deploy-prod.yml`), rewrite the
placeholder echo step into a real deploy job following `deploy-dev.yml`'s pattern (ECR push,
ECS update-service, register-task-definition, smoke test), and point it at the new prod ECS
cluster/service once Terraform `envs/prod/` is actually populated and applied.
