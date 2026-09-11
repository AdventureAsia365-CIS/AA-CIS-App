/**
 * AA-CIS API Smoke + Load Test
 * Routes: /health
 * Target: p95 < 5s, error rate < 1%
 *
 * AA-585 (2026-09-11): /tours and /tours/{tour_id} were deleted (unauthenticated
 * legacy routes leaking raw_tours data) — this script no longer exercises them.
 * The v1_tours.py equivalents require a real tenant JWT, so they aren't a drop-in
 * replacement for an unauthenticated smoke test; re-add tours coverage here only
 * if this script is extended to mint/pass a real tenant JWT.
 *
 * Usage:
 *   k6 run -e BASE_URL=http://localhost:8001 tests/load/k6_api_smoke_test.js
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8001";

const errorRate = new Rate("error_rate");

export const options = {
  scenarios: {
    smoke: {
      executor: "constant-vus",
      vus: 5,
      duration: "30s",
      tags: { scenario: "smoke" },
    },
    load: {
      executor: "constant-vus",
      vus: 50,
      duration: "60s",
      startTime: "40s",
      tags: { scenario: "load" },
    },
  },

  thresholds: {
    "http_req_duration{endpoint:health}":      ["p(95)<200",  "p(99)<500"],
    "http_req_failed": ["rate<0.01"],
    "http_req_duration": ["p(95)<5000"],
    "error_rate": ["rate<0.01"],
  },
};

export default function () {
  // ── Health ──────────────────────────────────────────────────
  group("health", () => {
    const res = http.get(`${BASE_URL}/health`, {
      tags: { endpoint: "health" },
    });
    const ok = check(res, {
      "health: 200":         (r) => r.status === 200,
      "health: status=ok":   (r) => r.json("status") === "ok",
      "health: has service": (r) => r.json("service") !== undefined,
    });
    errorRate.add(!ok ? 1 : 0);
  });

  sleep(0.5);
}

export function handleSummary(data) {
  const p95      = data.metrics["http_req_duration"]?.values?.["p(95)"] || 0;
  const errRate  = data.metrics["http_req_failed"]?.values?.rate || 0;
  const rps      = data.metrics["http_reqs"]?.values?.rate || 0;
  const passed   = p95 < 5000 && errRate < 0.01;

  console.log(`\n── API Smoke Test Summary ──`);
  console.log(`  Overall p95:  ${p95.toFixed(0)}ms  (target: <5000ms) ${p95 < 5000 ? "✓" : "✗"}`);
  console.log(`  Error rate:   ${(errRate * 100).toFixed(2)}%  (target: <1%) ${errRate < 0.01 ? "✓" : "✗"}`);
  console.log(`  Throughput:   ${rps.toFixed(1)} req/s`);
  console.log(`  Result:       ${passed ? "✓ PASS" : "✗ FAIL"}`);
  console.log(`───────────────────────────\n`);

  return {
    stdout: `p95=${p95.toFixed(0)}ms  errors=${(errRate*100).toFixed(2)}%  rps=${rps.toFixed(1)}  ${passed ? "PASS" : "FAIL"}`,
  };
}
