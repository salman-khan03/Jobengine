// Read-path load test: anonymous job browsing.
//
// This is the endpoint that actually gets hammered — every visitor hits
// /api/jobs before they ever create an account, and it is the one query that
// scans the ~32k-row jobs table. The write path lives in tracker.js.
//
// Run:
//   k6 run -e BASE_URL=http://localhost:8765 loadtest/k6/browse.js
//   k6 run -e BASE_URL=... -e PROFILE=stress loadtest/k6/browse.js
//
// Two profiles on purpose:
//   baseline — a load the service is expected to survive. Thresholds are
//              hard pass/fail here, so this can gate CI.
//   stress   — deliberately past the expected ceiling, to find *where* it
//              breaks and confirm it degrades into 503-with-Retry-After
//              rather than hanging. Thresholds are intentionally absent:
//              a stress run that "fails" is doing its job.

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:8765';
const PROFILE = __ENV.PROFILE || 'baseline';

// Pool-exhaustion backpressure is a *designed* response, not an error, so it
// gets its own metric instead of being buried in http_req_failed.
const shedRate = new Rate('requests_shed_503');
const jobsLatency = new Trend('jobs_latency_ms', true);

const PROFILES = {
  baseline: {
    stages: [
      { duration: '30s', target: 50 },   // ramp
      { duration: '2m', target: 50 },    // hold — this is the measured window
      { duration: '15s', target: 0 },
    ],
    thresholds: {
      // P95 target. Chosen from the SLO in docs/, not reverse-engineered from
      // whatever the service happened to do on the last run.
      'http_req_duration{expected_response:true}': ['p(95)<500'],
      http_req_failed: ['rate<0.01'],
      requests_shed_503: ['rate<0.01'],
    },
  },
  stress: {
    stages: [
      { duration: '30s', target: 100 },
      { duration: '30s', target: 200 },
      { duration: '1m', target: 300 },   // the interesting one
      { duration: '30s', target: 0 },
    ],
    thresholds: {},
  },
};

export const options = {
  scenarios: {
    browse: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: PROFILES[PROFILE].stages,
      gracefulRampDown: '10s',
    },
  },
  thresholds: PROFILES[PROFILE].thresholds,
};

// Realistic filter mix rather than one hot query repeated: a single identical
// query would sit in Postgres' cache and report latency no real user sees.
const FILTERS = [
  '?max=50',
  '?grad=intern&max=50',
  '?grad=newgrad&max=50',
  '?tier=very_high&max=50',
  '?tier=very_high,high&grad=intern&max=100',
  '?location=Remote&max=50',
  '?location=New%20York,Seattle&max=50',
];

export default function () {
  const filter = FILTERS[Math.floor(Math.random() * FILTERS.length)];
  const res = http.get(`${BASE}/api/jobs${filter}`, {
    tags: { name: 'GET /api/jobs' },
  });

  shedRate.add(res.status === 503);
  jobsLatency.add(res.timings.duration);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'body is a JSON array': (r) => {
      try { return Array.isArray(r.json()); } catch (_) { return false; }
    },
  });
}
