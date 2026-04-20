/**
 * AA-CIS Pipeline Load Test
 * PRD target: 10 concurrent batch uploads, p95 < 60s/tour end-to-end
 *
 * Usage:
 *   # Against staging
 *   k6 run -e BASE_URL=https://api-staging.aa-cis.internal k6_pipeline_load_test.js
 *
 *   # Against local dev
 *   k6 run -e BASE_URL=http://localhost:8000 k6_pipeline_load_test.js
 *
 *   # CI (fail fast thresholds)
 *   k6 run --out json=results.json -e BASE_URL=$STAGING_URL k6_pipeline_load_test.js
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Trend, Counter, Rate } from "k6/metrics";
import { SharedArray } from "k6/data";
import encoding from "k6/encoding";

// ── Custom metrics ────────────────────────────────────────────────
const tourProcessingTime = new Trend("tour_processing_time_ms", true);
const batchUploadTime    = new Trend("batch_upload_time_ms", true);
const pipelineE2ETime    = new Trend("pipeline_e2e_time_ms", true);
const uploadErrors       = new Counter("upload_errors");
const statusPollCount    = new Counter("status_poll_count");
const tourPassRate       = new Rate("tour_pass_rate");
const cacheHitRate       = new Rate("seo_cache_hit_rate");

// ── Test config ───────────────────────────────────────────────────
const BASE_URL   = __ENV.BASE_URL   || "http://localhost:8000";
const API_KEY    = __ENV.API_KEY    || "wl_live_sk_test_internal";
const TOURS_PER_BATCH = parseInt(__ENV.TOURS_PER_BATCH || "5");

// ── Thresholds (PRD S6 done criteria) ────────────────────────────
export const options = {
  scenarios: {
    // Scenario 1: 10 concurrent batch uploads (PRD Plan v3 target)
    concurrent_batches: {
      executor: "constant-vus",
      vus: 10,
      duration: "3m",
      tags: { scenario: "concurrent_batches" },
    },

    // Scenario 2: Ramp-up — test ECS auto-scale trigger
    ramp_up: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 5  },   // warm up
        { duration: "60s", target: 10 },   // PRD target
        { duration: "30s", target: 20 },   // stress — verify no crash
        { duration: "30s", target: 0  },   // cool down
      ],
      startTime: "3m30s",                  // starts after concurrent_batches
      tags: { scenario: "ramp_up" },
    },
  },

  thresholds: {
    // PRD S6 done criteria: p95 < 60s per tour end-to-end
    "pipeline_e2e_time_ms{scenario:concurrent_batches}": [
      { threshold: "p(95)<60000", abortOnFail: true },
    ],

    // API endpoints: p95 < 5s (deploy-staging.yml gate)
    "http_req_duration{endpoint:upload}":       ["p(95)<5000"],
    "http_req_duration{endpoint:status}":       ["p(95)<500"],
    "http_req_duration{endpoint:health}":       ["p(95)<200"],
    "http_req_duration{endpoint:catalog}":      ["p(95)<1000"],

    // Error rate: < 1% (prod auto-rollback trigger)
    "http_req_failed": ["rate<0.01"],

    // Upload specifically: < 2% errors
    "upload_errors": ["count<5"],

    // Tour pass rate: > 85% (quality gate)
    "tour_pass_rate": ["rate>0.85"],
  },
};

// ── Auth header ───────────────────────────────────────────────────
function authHeaders(extra = {}) {
  return {
    "X-API-Key":   API_KEY,
    "Content-Type": "application/json",
    ...extra,
  };
}

// ── Minimal Excel-like payload (base64 stub) ──────────────────────
// In real staging: replace with actual .xlsx binary from S3 presigned URL
function makeBatchPayload(vuId, iteration) {
  const tours = Array.from({ length: TOURS_PER_BATCH }, (_, i) => ({
    src_name:      `VU${vuId}_ITER${iteration}_TOUR_${i + 1} ALL CAPS NAME`,
    src_subtitle:  `Destination City, Country`,
    src_summary:   `A supplier-written description of tour ${i + 1} for VU ${vuId}.`,
    src_highlights: ["Highlight one", "Highlight two", "Highlight three"],
    src_itineraries: [
      { day: 1, title: "Arrival", description: "Arrive and check in." },
      { day: 2, title: "Tour",    description: "Full day tour." },
    ],
    country: "Vietnam",
    vendor:  `vendor_vu${vuId}`,
    market:  "en_US",
  }));

  return JSON.stringify({
    batch_id: `load-test-vu${vuId}-iter${iteration}-${Date.now()}`,
    tenant_id: "aa_internal",
    tours,
  });
}

// ── Scenario: health check (always run as baseline) ───────────────
export function healthCheck() {
  const res = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: "health" },
  });
  check(res, {
    "health: status 200":    (r) => r.status === 200,
    "health: body has ok":   (r) => r.json("status") === "ok",
    "health: db connected":  (r) => r.json("db") === "connected",
    "health: redis connected": (r) => r.json("redis") === "connected",
  });
}

// ── Poll pipeline status until complete or timeout ────────────────
function pollPipelineStatus(batchId, timeoutMs = 90000) {
  const pollInterval = 2000; // 2s — matches Content UI polling
  const maxPolls     = timeoutMs / pollInterval;
  let   polls        = 0;
  let   finalStatus  = "unknown";

  while (polls < maxPolls) {
    statusPollCount.add(1);
    const res = http.get(
      `${BASE_URL}/api/v1/pipeline/status/${batchId}`,
      { headers: authHeaders(), tags: { endpoint: "status" } }
    );

    if (res.status !== 200) {
      sleep(pollInterval / 1000);
      polls++;
      continue;
    }

    const body = res.json();
    finalStatus = body.status;

    if (["completed", "failed", "dlq"].includes(finalStatus)) {
      return {
        status:       finalStatus,
        toursTotal:   body.tours_total   || 0,
        toursPassed:  body.tours_passed  || 0,
        toursHITL:    body.tours_hitl    || 0,
        toursFailed:  body.tours_failed  || 0,
        costUsd:      body.cost_usd      || 0,
        cacheHit:     body.seo_cache_hit || false,
        polls,
      };
    }

    sleep(pollInterval / 1000);
    polls++;
  }

  return { status: "timeout", polls };
}

// ── Main VU function ──────────────────────────────────────────────
export default function () {
  const vuId     = __VU;
  const iter     = __ITER;

  group("health_check", () => {
    healthCheck();
  });

  group("batch_upload_and_poll", () => {
    // ── Step 1: Upload batch ──────────────────────────────────────
    const payload    = makeBatchPayload(vuId, iter);
    const uploadStart = Date.now();

    const uploadRes = http.post(
      `${BASE_URL}/api/v1/pipeline/upload`,
      payload,
      {
        headers: authHeaders(),
        tags:    { endpoint: "upload" },
        timeout: "10s",
      }
    );

    batchUploadTime.add(Date.now() - uploadStart);

    const uploadOk = check(uploadRes, {
      "upload: status 202":       (r) => r.status === 202,
      "upload: has batch_id":     (r) => r.json("batch_id") !== undefined,
      "upload: has run_id":       (r) => r.json("run_id")   !== undefined,
      "upload: status=queued":    (r) => r.json("status")   === "queued",
    });

    if (!uploadOk) {
      uploadErrors.add(1);
      return;
    }

    const batchId = uploadRes.json("batch_id");
    const e2eStart = Date.now();

    // ── Step 2: Poll until pipeline completes ─────────────────────
    const result = pollPipelineStatus(batchId);
    const e2eMs  = Date.now() - e2eStart;

    pipelineE2ETime.add(e2eMs);
    // Per-tour processing time
    if (result.toursTotal > 0) {
      tourProcessingTime.add(e2eMs / result.toursTotal);
    }

    check(result, {
      "pipeline: completed (not timeout)": (r) => r.status === "completed",
      "pipeline: no tours in DLQ":         (r) => r.status !== "dlq",
    });

    // Pass rate metric
    if (result.toursTotal > 0) {
      const passed = result.toursPassed / result.toursTotal >= 0.85;
      tourPassRate.add(passed);
    }

    // SEO cache hit (second+ iteration should hit cache)
    if (iter > 0) {
      cacheHitRate.add(result.cacheHit ? 1 : 0);
    }

    // Cost sanity check: < $0.032/tour (10% buffer over $0.029 target)
    if (result.toursTotal > 0 && result.costUsd > 0) {
      const costPerTour = result.costUsd / result.toursTotal;
      check({ costPerTour }, {
        "cost: < $0.032/tour": (c) => c.costPerTour < 0.032,
      });
    }
  });

  group("catalog_read", () => {
    // ── Step 3: Verify published tours appear in catalog ──────────
    const catalogRes = http.get(
      `${BASE_URL}/api/v1/catalog?tenant_id=aa_internal&limit=10`,
      {
        headers: authHeaders(),
        tags:    { endpoint: "catalog" },
      }
    );

    check(catalogRes, {
      "catalog: status 200":       (r) => r.status === 200,
      "catalog: has tours array":  (r) => Array.isArray(r.json("tours")),
      "catalog: has total_count":  (r) => r.json("total_count") !== undefined,
    });
  });

  sleep(1);
}

// ── Teardown: print summary ───────────────────────────────────────
export function handleSummary(data) {
  const passed  = data.metrics.tour_pass_rate?.values?.rate  || 0;
  const p95e2e  = data.metrics.pipeline_e2e_time_ms?.values?.["p(95)"] || 0;
  const p95api  = data.metrics["http_req_duration{endpoint:upload}"]?.values?.["p(95)"] || 0;
  const errors  = data.metrics.http_req_failed?.values?.rate || 0;
  const polls   = data.metrics.status_poll_count?.values?.count || 0;

  const summary = {
    timestamp:       new Date().toISOString(),
    environment:     BASE_URL,
    results: {
      tour_pass_rate:        `${(passed * 100).toFixed(1)}%  (target: >85%)`,
      pipeline_e2e_p95_ms:   `${p95e2e.toFixed(0)}ms  (target: <60000ms)`,
      api_upload_p95_ms:     `${p95api.toFixed(0)}ms  (target: <5000ms)`,
      http_error_rate:       `${(errors * 100).toFixed(2)}%  (target: <1%)`,
      status_poll_total:     polls,
    },
    thresholds_passed: !data.metrics.pipeline_e2e_time_ms?.thresholds?.["p(95)<60000"]?.ok === false,
  };

  console.log("\n─────────────────────────────────────────");
  console.log("  AA-CIS LOAD TEST SUMMARY");
  console.log("─────────────────────────────────────────");
  console.log(JSON.stringify(summary.results, null, 2));
  console.log("─────────────────────────────────────────\n");

  return {
    "tests/load/results/k6_summary.json": JSON.stringify(summary, null, 2),
    stdout: JSON.stringify(summary.results, null, 2),
  };
}
