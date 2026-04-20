# AA-CIS Load Tests

k6 load test suite for S6. Three scripts, three purposes.

## Scripts

| File | Purpose | When |
|------|---------|------|
| `k6_api_smoke_test.js` | API endpoint latency, 50 VUs, p95 < 5s | `deploy-staging.yml` |
| `k6_pipeline_load_test.js` | 10 concurrent batch uploads, p95 < 60s/tour | `deploy-staging.yml` (after smoke) |
| `k6_golden_regression.js` | 20 golden tours, quality score vs baseline | `lesson-regression.yml` (weekly) |

## Install k6

```bash
# Ubuntu / WSL2
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
    --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
    | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt update && sudo apt install k6
```

## Run locally (against dev server)

```bash
# Start FastAPI dev server first
cd AA-CIS-App && uvicorn app.main:app --reload --port 8000

# Smoke test (fast, ~2 min)
k6 run -e BASE_URL=http://localhost:8000 tests/load/k6_api_smoke_test.js

# Pipeline load test (10 concurrent batches, ~5 min)
k6 run -e BASE_URL=http://localhost:8000 \
       -e TOURS_PER_BATCH=3 \
       tests/load/k6_pipeline_load_test.js

# Golden regression (20 tours sequential, ~20 min)
k6 run -e BASE_URL=http://localhost:8000 \
       -e BASELINE_SCORE=8.0 \
       tests/load/k6_golden_regression.js
```

## Run against staging

```bash
export STAGING_URL=https://api-staging.aa-cis.internal
export API_KEY=wl_live_sk_staging_xxxxx

k6 run -e BASE_URL=$STAGING_URL -e API_KEY=$API_KEY \
       --out json=tests/load/results/smoke.json \
       tests/load/k6_api_smoke_test.js

k6 run -e BASE_URL=$STAGING_URL -e API_KEY=$API_KEY \
       --out json=tests/load/results/pipeline.json \
       tests/load/k6_pipeline_load_test.js
```

## Thresholds (CI gate — auto-fail if breached)

| Metric | Target | Script |
|--------|--------|--------|
| `pipeline_e2e_time_ms p95` | < 60,000ms | pipeline |
| `http_req_duration p95` (all endpoints) | < 5,000ms | smoke |
| `http_req_failed rate` | < 1% | both |
| `tour_pass_rate` | > 85% | pipeline |
| Quality score drop | ≤ 0.5 vs baseline | regression |

## GitHub Actions integration

`deploy-staging.yml`:
```yaml
- name: Load test — API smoke
  run: |
    k6 run -e BASE_URL=${{ secrets.STAGING_URL }} \
           -e API_KEY=${{ secrets.STAGING_API_KEY }} \
           tests/load/k6_api_smoke_test.js

- name: Load test — Pipeline
  run: |
    k6 run -e BASE_URL=${{ secrets.STAGING_URL }} \
           -e API_KEY=${{ secrets.STAGING_API_KEY }} \
           tests/load/k6_pipeline_load_test.js
```

`lesson-regression.yml` (weekly):
```yaml
- name: Golden dataset regression
  run: |
    k6 run -e BASE_URL=${{ secrets.PROD_URL }} \
           -e API_KEY=${{ secrets.PROD_API_KEY }} \
           -e BASELINE_SCORE=${{ vars.QUALITY_BASELINE }} \
           tests/load/k6_golden_regression.js
```

## Results

Results saved to `tests/load/results/` (gitignored).
CI publishes results as GitHub Actions artifacts.
