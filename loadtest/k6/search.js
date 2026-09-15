// Load test for the Spring Boot search API.
//
// Run (no local k6 install needed):
//   docker run --rm -i --network jobengine-net -v "$PWD/loadtest:/lt" grafana/k6 \
//     run -e BASE_URL=http://jobengine-java:8080 /lt/k6/search.js
//
// PROFILE=baseline (default) | stress
//
// The filter mix below is deliberately head-heavy — roughly 70% of traffic hits
// a small set of popular filter combinations, which is what real job-search
// traffic looks like and what makes a cache worth having. A uniform random mix
// would understate the hit rate to the point of being misleading.

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:58080';
const PROFILE = __ENV.PROFILE || 'baseline';

const rateLimited = new Rate('requests_rate_limited_429');
const searchLatency = new Trend('search_latency_ms', true);

const PROFILES = {
  baseline: {
    stages: [
      { duration: '20s', target: 30 },
      { duration: '1m', target: 30 },
      { duration: '10s', target: 0 },
    ],
    thresholds: {
      'http_req_duration{expected_response:true}': ['p(95)<300'],
      http_req_failed: ['rate<0.01'],
    },
  },
  stress: {
    stages: [
      { duration: '20s', target: 100 },
      { duration: '30s', target: 200 },
      { duration: '1m', target: 300 },
      { duration: '20s', target: 0 },
    ],
    thresholds: {},
  },
};

// To measure the UNCACHED database path, do not try to defeat the cache from
// the generator side — turn the cache off:
//
//   SPRING_CACHE_TYPE=none  (see RedisCacheConfig's @ConditionalOnProperty)
//
// An earlier "cachecold" profile here cycled a unique offset per iteration,
// which looked cold but produced only 200 distinct cache keys and so warmed up
// within the first fraction of a second — it reported a 99.93% hit rate while
// claiming to be a cold-cache run. It was removed rather than left as a trap.

export const options = {
  scenarios: {
    search: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: PROFILES[PROFILE].stages,
      gracefulRampDown: '10s',
    },
  },
  thresholds: PROFILES[PROFILE].thresholds,
};

// Real tier values as produced by sponsor_index.py — not invented ones.
const HOT = [
  '?tier=very_high&tier=high&limit=50',
  '?tier=very_high&limit=50',
  '?seniority=NEW_GRAD&tier=very_high&limit=50',
  '?seniority=INTERN&limit=50',
  '?location=remote&limit=50',
];
const COLD = [
  '?company=amazon&limit=50',
  '?company=microsoft&limit=50',
  '?skill=kubernetes&limit=50',
  '?skill=python&limit=50',
  '?location=seattle&limit=50',
  '?location=new%20york&limit=50',
  '?seniority=NEW_GRAD&location=austin&limit=50',
];

export default function () {
  const path = Math.random() < 0.7
    ? HOT[Math.floor(Math.random() * HOT.length)]
    : COLD[Math.floor(Math.random() * COLD.length)];

  const res = http.get(`${BASE}/api/v1/jobs${path}`, {
    headers: { 'X-API-Key': __ENV.API_KEY || 'dev-key-not-for-production' },
    tags: { name: 'GET /api/v1/jobs' },
  });

  rateLimited.add(res.status === 429);
  searchLatency.add(res.timings.duration);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'body is an array': (r) => {
      try { return Array.isArray(r.json()); } catch (_) { return false; }
    },
  });
}
