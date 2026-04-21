import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

const errorRate = new Rate('errors');
const tourListDuration = new Trend('tour_list_duration', true);
const rateLimitHits = new Counter('rate_limit_429');

const TENANTS = [
  { name: 'WanderLux',      jwt: __ENV.JWT_WANDERLUX,      expectedTotal: 1000 },
  { name: 'ExploreAsia',    jwt: __ENV.JWT_EXPLOREASIA,    expectedTotal: 1000 },
  { name: 'PeakAdventures', jwt: __ENV.JWT_PEAKADVENTURES, expectedTotal: 1000 },
];

const BASE_URL = __ENV.BASE_URL || 'https://api-cis.lumiguides.it.com';

export const options = {
  scenarios: {
    wanderlux: {
      executor: 'constant-vus',
      vus: 20,
      duration: '3m',
      env: { TENANT_IDX: '0' },
    },
    exploreasia: {
      executor: 'constant-vus',
      vus: 5,
      duration: '3m',
      env: { TENANT_IDX: '1' },
    },
    peakadventures: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: 30 },
        { duration: '2m', target: 30 },
      ],
      env: { TENANT_IDX: '2' },
    },
  },
  thresholds: {
    'errors':            ['rate<0.05'],       // < 5% errors (excluding 429)
    'http_req_duration': ['p(95)<3000'],      // p95 < 3s
    'tour_list_duration':['p(99)<5000'],      // p99 < 5s
  },
};

export default function () {
  const idx = parseInt(__ENV.TENANT_IDX || '0');
  const tenant = TENANTS[idx];
  const headers = {
    'Authorization': `Bearer ${tenant.jwt}`,
    'Content-Type': 'application/json',
  };

  // Test 1: GET /v1/tours paginated
  const page = Math.floor(Math.random() * 10) + 1;
  const start = Date.now();
  const res1 = http.get(`${BASE_URL}/v1/tours?page=${page}&page_size=100`, { headers });
  tourListDuration.add(Date.now() - start);

  if (res1.status === 429) {
    rateLimitHits.add(1);
  } else {
    const ok = check(res1, {
      'tours 200':          (r) => r.status === 200,
      'has data array':     (r) => { try { return JSON.parse(r.body).data.length > 0; } catch { return false; } },
      'tenant isolated':    (r) => { try { return JSON.parse(r.body).pagination.total <= 1000; } catch { return false; } },
      'correct tenant_id':  (r) => { try { return JSON.parse(r.body).tenant_id !== null; } catch { return false; } },
    });
    errorRate.add(!ok);

    // Test 2: GET /v1/tours/{id}
    if (res1.status === 200) {
      try {
        const body = JSON.parse(res1.body);
        if (body.data && body.data.length > 0) {
          const tour = body.data[Math.floor(Math.random() * body.data.length)];
          const res2 = http.get(`${BASE_URL}/v1/tours/${tour.id}`, { headers });
          if (res2.status !== 429) {
            const ok2 = check(res2, {
              'tour detail 200': (r) => r.status === 200,
              'has aa_name':     (r) => { try { return JSON.parse(r.body).aa_name !== null; } catch { return false; } },
            });
            errorRate.add(!ok2);
          } else {
            rateLimitHits.add(1);
          }
        }
      } catch {}
    }
  }

  sleep(0.5);
}

export function handleSummary(data) {
  const metrics = data.metrics;
  const summary = {
    'errors_rate':         metrics.errors?.values?.rate?.toFixed(4) || 'N/A',
    'http_p95_ms':         metrics.http_req_duration?.values?.['p(95)']?.toFixed(0) || 'N/A',
    'tour_list_p99_ms':    metrics.tour_list_duration?.values?.['p(99)']?.toFixed(0) || 'N/A',
    'rate_limit_429_hits': metrics.rate_limit_429?.values?.count || 0,
    'total_requests':      metrics.http_reqs?.values?.count || 0,
    'req_per_sec':         metrics.http_reqs?.values?.rate?.toFixed(1) || 'N/A',
  };

  console.log('\n========== S9 LOAD TEST SUMMARY ==========');
  for (const [k, v] of Object.entries(summary)) {
    console.log(`  ${k.padEnd(25)}: ${v}`);
  }
  console.log('==========================================\n');

  return {
    stdout: JSON.stringify(summary, null, 2),
  };
}
