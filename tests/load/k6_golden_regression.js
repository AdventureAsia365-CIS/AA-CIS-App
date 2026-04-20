/**
 * AA-CIS Golden Dataset Regression Test
 * PRD: Weekly CI — run 20 golden tours, compare avg quality_score vs baseline.
 * Alert if drop > 0.5 (lesson-regression.yml)
 *
 * Usage:
 *   k6 run -e BASE_URL=https://api-staging.aa-cis.internal \
 *          -e BASELINE_SCORE=8.2 \
 *          k6_golden_regression.js
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE_URL       = __ENV.BASE_URL       || "http://localhost:8000";
const API_KEY        = __ENV.API_KEY        || "wl_live_sk_test_internal";
const BASELINE_SCORE = parseFloat(__ENV.BASELINE_SCORE || "8.0");
const SCORE_DROP_THRESHOLD = 0.5;   // PRD: alert if avg drops > 0.5

const qualityScore  = new Trend("quality_score");
const passRate      = new Rate("golden_pass_rate");
const processingMs  = new Trend("golden_processing_ms", true);

export const options = {
  // Sequential — one VU processes all 20 golden tours
  scenarios: {
    golden_regression: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "30m",   // PRD: < 30 min
    },
  },

  thresholds: {
    // Quality gate: avg score must not drop > 0.5 vs baseline
    // k6 can't compare against dynamic baseline directly — handled in handleSummary
    "golden_pass_rate":     ["rate>0.85"],
    "http_req_failed":      ["rate<0.01"],
    "golden_processing_ms": ["p(95)<120000"], // 2 min max per tour
  },
};

function headers() {
  return { "X-API-Key": API_KEY, "Content-Type": "application/json" };
}

// 20 golden tour payloads — representative of real vendor data
const GOLDEN_TOURS = [
  { id: "g01", country: "Vietnam",   name: "HA LONG BAY OVERNIGHT CRUISE",        market: "en_US" },
  { id: "g02", country: "Vietnam",   name: "HOI AN LANTERN FESTIVAL TOUR",        market: "en_US" },
  { id: "g03", country: "Vietnam",   name: "HO CHI MINH CITY FOOD TOUR",         market: "en_AU" },
  { id: "g04", country: "Thailand",  name: "CHIANG MAI ELEPHANT SANCTUARY",       market: "en_US" },
  { id: "g05", country: "Thailand",  name: "PHUKET ISLAND HOPPING TOUR",         market: "en_UK" },
  { id: "g06", country: "Thailand",  name: "BANGKOK TEMPLE AND MARKET TOUR",     market: "en_US" },
  { id: "g07", country: "Cambodia",  name: "ANGKOR WAT SUNRISE PRIVATE TOUR",    market: "en_AU" },
  { id: "g08", country: "Cambodia",  name: "SIEM REAP COUNTRYSIDE BIKE TOUR",    market: "en_US" },
  { id: "g09", country: "Indonesia", name: "BALI RICE TERRACES CYCLING TOUR",    market: "en_US" },
  { id: "g10", country: "Indonesia", name: "KOMODO ISLAND DIVING ADVENTURE",     market: "en_AU" },
  { id: "g11", country: "Myanmar",   name: "BAGAN TEMPLES HOT AIR BALLOON",      market: "en_US" },
  { id: "g12", country: "Laos",      name: "LUANG PRABANG MONKS BLESSING TOUR",  market: "en_UK" },
  { id: "g13", country: "Japan",     name: "KYOTO GEISHA DISTRICT WALKING TOUR", market: "en_US" },
  { id: "g14", country: "Japan",     name: "MT FUJI SUNRISE HIKING TOUR",        market: "en_AU" },
  { id: "g15", country: "Nepal",     name: "EVEREST BASE CAMP TREKKING 14 DAYS", market: "en_US" },
  { id: "g16", country: "India",     name: "TAJ MAHAL SUNRISE PRIVATE TOUR",     market: "en_UK" },
  { id: "g17", country: "Sri Lanka", name: "SIGIRIYA ROCK AND DAMBULLA CAVE",    market: "en_US" },
  { id: "g18", country: "Malaysia",  name: "BORNEO ORANGUTAN RIVER SAFARI",      market: "en_AU" },
  { id: "g19", country: "Philippines", name: "PALAWAN ISLAND HOPPING EL NIDO",   market: "en_US" },
  { id: "g20", country: "Singapore", name: "SINGAPORE HAWKER FOOD NIGHT TOUR",   market: "en_US" },
];

function buildTourPayload(tour) {
  return JSON.stringify({
    batch_id:  `golden-regression-${tour.id}-${Date.now()}`,
    tenant_id: "aa_internal",
    is_regression_test: true,
    golden_tour_id: tour.id,
    tours: [{
      src_name:      tour.name,
      src_subtitle:  `${tour.country} destination`,
      src_summary:   `Supplier description for ${tour.name}. This tour explores the highlights of ${tour.country}.`,
      src_highlights: ["Activity one", "Activity two", "Activity three"],
      src_itineraries: [
        { day: 1, title: "Arrival",   description: "Arrive and transfer to hotel." },
        { day: 2, title: "Main Tour", description: "Full day guided tour." },
      ],
      country: tour.country,
      vendor:  "golden_dataset",
      market:  tour.market,
    }],
  });
}

function pollUntilDone(batchId, timeoutMs = 120000) {
  const interval = 3000;
  const maxPolls = timeoutMs / interval;
  let   polls    = 0;

  while (polls < maxPolls) {
    const res = http.get(
      `${BASE_URL}/api/v1/pipeline/status/${batchId}`,
      { headers: headers() }
    );

    if (res.status === 200) {
      const body = res.json();
      if (["completed", "failed", "dlq"].includes(body.status)) {
        return body;
      }
    }
    sleep(interval / 1000);
    polls++;
  }
  return { status: "timeout" };
}

export default function () {
  const scores  = [];
  const results = [];

  for (const tour of GOLDEN_TOURS) {
    console.log(`Processing golden tour ${tour.id}: ${tour.name}`);
    const start = Date.now();

    // Upload
    const uploadRes = http.post(
      `${BASE_URL}/api/v1/pipeline/upload`,
      buildTourPayload(tour),
      { headers: headers(), timeout: "10s" }
    );

    if (uploadRes.status !== 202) {
      console.error(`  ✗ Upload failed for ${tour.id}: HTTP ${uploadRes.status}`);
      results.push({ id: tour.id, status: "upload_failed", score: 0 });
      continue;
    }

    const batchId = uploadRes.json("batch_id");

    // Poll
    const result = pollUntilDone(batchId);
    const elapsed = Date.now() - start;
    processingMs.add(elapsed);

    if (result.status === "timeout") {
      console.error(`  ✗ Timeout for ${tour.id} after ${elapsed}ms`);
      results.push({ id: tour.id, status: "timeout", score: 0 });
      continue;
    }

    // Get quality score for the processed tour
    const scoreRes = http.get(
      `${BASE_URL}/api/v1/pipeline/batch/${batchId}/scores`,
      { headers: headers() }
    );

    let score = 0;
    if (scoreRes.status === 200) {
      const tourScores = scoreRes.json("scores") || [];
      if (tourScores.length > 0) {
        score = tourScores[0].overall_score || 0;
      }
    }

    qualityScore.add(score);
    passRate.add(result.status === "completed" && score >= BASELINE_SCORE - SCORE_DROP_THRESHOLD ? 1 : 0);

    const passed = result.status === "completed";
    check(result, {
      [`${tour.id}: completed`]: (r) => r.status === "completed",
      [`${tour.id}: not in DLQ`]: (r) => r.status !== "dlq",
    });

    results.push({
      id:       tour.id,
      country:  tour.country,
      status:   result.status,
      score,
      passed,
      elapsed_ms: elapsed,
    });

    console.log(`  ${passed ? "✓" : "✗"} ${tour.id} — score: ${score.toFixed(2)}, time: ${(elapsed/1000).toFixed(1)}s`);
    sleep(1);
  }

  // Store results for handleSummary
  // k6 doesn't have global state — log to console for CI parsing
  const avgScore  = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  const passCount = results.filter((r) => r.passed).length;

  console.log(`\n── Golden Dataset Results ──`);
  console.log(`  Total tours:  ${results.length}/20`);
  console.log(`  Passed:       ${passCount}/${results.length}`);
  console.log(`  Avg score:    ${avgScore.toFixed(2)}  (baseline: ${BASELINE_SCORE})`);
  console.log(`  Score drop:   ${(BASELINE_SCORE - avgScore).toFixed(2)}  (threshold: ${SCORE_DROP_THRESHOLD})`);

  if (BASELINE_SCORE - avgScore > SCORE_DROP_THRESHOLD) {
    console.error(`\n  ⚠ REGRESSION DETECTED: avg score dropped ${(BASELINE_SCORE - avgScore).toFixed(2)} points`);
  }
}

export function handleSummary(data) {
  const avgScore  = data.metrics.quality_score?.values?.avg || 0;
  const p50Score  = data.metrics.quality_score?.values?.["p(50)"] || 0;
  const passRate_ = data.metrics.golden_pass_rate?.values?.rate || 0;
  const p95ms     = data.metrics.golden_processing_ms?.values?.["p(95)"] || 0;

  const scoreDrop     = BASELINE_SCORE - avgScore;
  const regressionFlag = scoreDrop > SCORE_DROP_THRESHOLD;

  const summary = {
    timestamp:        new Date().toISOString(),
    baseline_score:   BASELINE_SCORE,
    avg_score:        avgScore,
    p50_score:        p50Score,
    score_drop:       scoreDrop,
    regression_detected: regressionFlag,
    pass_rate_pct:    (passRate_ * 100).toFixed(1),
    p95_processing_ms: p95ms,
    ci_exit_code:     regressionFlag ? 1 : 0,
  };

  console.log("\n─────────────────────────────────────────");
  console.log("  GOLDEN DATASET REGRESSION SUMMARY");
  console.log("─────────────────────────────────────────");
  console.log(`  Avg score:    ${avgScore.toFixed(2)}  (baseline: ${BASELINE_SCORE})`);
  console.log(`  Score drop:   ${scoreDrop.toFixed(2)}  (threshold: ${SCORE_DROP_THRESHOLD})`);
  console.log(`  Regression:   ${regressionFlag ? "⚠ YES — CI FAIL" : "✓ NO"}`);
  console.log(`  Pass rate:    ${(passRate_ * 100).toFixed(1)}%`);
  console.log("─────────────────────────────────────────\n");

  return {
    "tests/load/results/k6_regression_summary.json": JSON.stringify(summary, null, 2),
    stdout: `regression=${regressionFlag}  avg_score=${avgScore.toFixed(2)}  baseline=${BASELINE_SCORE}`,
  };
}
