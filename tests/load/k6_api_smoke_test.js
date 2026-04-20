/**
 * AA-CIS API Smoke + Load Test
 * Routes: /health, /tours, /tours/{tour_id}
 * Target: p95 < 5s, error rate < 1%
 *
 * Usage:
 *   k6 run -e BASE_URL=http://localhost:8001 tests/load/k6_api_smoke_test.js
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8001";
const API_KEY  = __ENV.API_KEY  || "";

const toursLatency = new Trend("tours_list_latency_ms", true);
const tourLatency  = new Trend("tour_detail_latency_ms", true);
const errorRate    = new Rate("error_rate");

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
    "http_req_duration{endpoint:tours}":       ["p(95)<1000", "p(99)<3000"],
    "http_req_duration{endpoint:tour_detail}": ["p(95)<1000"],
    "http_req_failed": ["rate<0.01"],
    "http_req_duration": ["p(95)<5000"],
    "error_rate": ["rate<0.01"],
  },
};

function headers() {
  const h = { "Content-Type": "application/json" };
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}

let cachedTourId = null;

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

  // ── Tours list ──────────────────────────────────────────────
  group("tours_list", () => {
    const start = Date.now();
    const res = http.get(`${BASE_URL}/tours`, {
      headers: headers(),
      tags: { endpoint: "tours" },
    });
    toursLatency.add(Date.now() - start);

    const ok = check(res, {
      "tours: 200":     (r) => r.status === 200,
      "tours: not 500": (r) => r.status !== 500,
      "tours: has data":(r) => r.json("data") !== undefined,
    });
    errorRate.add(!ok ? 1 : 0);

    // Cache first tour_id from data array
    if (res.status === 200 && !cachedTourId) {
      try {
        const data = res.json("data");
        if (Array.isArray(data) && data.length > 0) {
          cachedTourId = data[0].tour_id || data[0].id;
        }
      } catch (_) {}
    }
  });

  // ── Tour detail ─────────────────────────────────────────────
  group("tour_detail", () => {
    // Skip if no tour in DB yet — don't generate errors for empty DB
    if (!cachedTourId) {
      return;
    }

    const start = Date.now();
    const res = http.get(`${BASE_URL}/tours/${cachedTourId}`, {
      headers: headers(),
      tags: { endpoint: "tour_detail" },
    });
    tourLatency.add(Date.now() - start);

    const ok = check(res, {
      "tour detail: 200":     (r) => r.status === 200,
      "tour detail: not 500": (r) => r.status !== 500,
      "tour detail: fast":    (r) => r.timings.duration < 1000,
    });
    errorRate.add(!ok ? 1 : 0);
  });

  sleep(0.5);
}

export function handleSummary(data) {
  const p95      = data.metrics["http_req_duration"]?.values?.["p(95)"] || 0;
  const errRate  = data.metrics["http_req_failed"]?.values?.rate || 0;
  const rps      = data.metrics["http_reqs"]?.values?.rate || 0;
  const p95tours = data.metrics["tours_list_latency_ms"]?.values?.["p(95)"] || 0;
  const passed   = p95 < 5000 && errRate < 0.01;

  console.log(`\n── API Smoke Test Summary ──`);
  console.log(`  Overall p95:  ${p95.toFixed(0)}ms  (target: <5000ms) ${p95 < 5000 ? "✓" : "✗"}`);
  console.log(`  /tours p95:   ${p95tours.toFixed(0)}ms  (target: <1000ms) ${p95tours < 1000 ? "✓" : "✗"}`);
  console.log(`  Error rate:   ${(errRate * 100).toFixed(2)}%  (target: <1%) ${errRate < 0.01 ? "✓" : "✗"}`);
  console.log(`  Throughput:   ${rps.toFixed(1)} req/s`);
  console.log(`  Result:       ${passed ? "✓ PASS" : "✗ FAIL"}`);
  console.log(`───────────────────────────\n`);

  return {
    stdout: `p95=${p95.toFixed(0)}ms  errors=${(errRate*100).toFixed(2)}%  rps=${rps.toFixed(1)}  ${passed ? "PASS" : "FAIL"}`,
  };
}
