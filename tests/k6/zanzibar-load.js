// K8s-6 Zanzibar Load Test — S3 Stability Soak k6 profile
//
// Source: Zanzibar-25 k6 pattern (dev repo platform-ssot tests/k6) K8s-6 port
// Hedef: S3 stability soak sırasında 50 VU × 6dk steady load
//
// Run:
//   export HOST=testai.acik.com
//   export CLIENT_SECRET=<vault kv/platform/keycloak/smoke-client>
//   k6 run tests/k6/zanzibar-load.js
//
// Prereq:
//   - S2-B3 smoke-client Keycloak confidential client merged
//   - Vault kv/platform/keycloak/smoke-client seed
//   - testai.acik.com (veya ai.acik.com D32 sonrası) edge reachable
//
// Thresholds (S3 No-Go gate):
//   - http_req_failed < 1%
//   - http_req_duration p95 < 2s
//   - deny_rate 100% (401 beklenir unauthenticated)
//   - allow_rate > 99% (2xx beklenir authenticated)
//
// Codex iter-6 yedek iş (d) — repo-side, canlı apply değil.

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate } from 'k6/metrics';

const HOST = __ENV.HOST || 'testai.acik.com';
const CLIENT_SECRET = __ENV.CLIENT_SECRET || '';
const CLIENT_ID = __ENV.CLIENT_ID || 'smoke-client';
const REALM = __ENV.REALM || 'serban';

if (!CLIENT_SECRET) {
  throw new Error(
    'CLIENT_SECRET env var zorunlu. Vault kv/platform/keycloak/smoke-client ' +
    'yolundan secret al. Örnek: export CLIENT_SECRET=$(vault kv get -field=CLIENT_SECRET kv/platform/keycloak/smoke-client)'
  );
}

export const options = {
  stages: [
    { duration: '2m', target: 20 },   // ramp-up 2m → 20 VU
    { duration: '6m', target: 50 },   // steady 6m @ 50 VU
    { duration: '2m', target: 0 },    // ramp-down 2m
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],           // %1 hata altı
    http_req_duration: ['p(95)<2000'],        // p95 < 2s
    'deny_rate': ['rate>=0.99'],              // %99 401 deny
    'allow_rate': ['rate>=0.99'],             // %99 2xx allow
    'token_acquire_rate': ['rate>=0.99'],     // %99 token al PASS
  },
  insecureSkipTLSVerify: true,    // testai/prod edge Sectigo wildcard cert
};

// Custom metrics
const denyRate = new Rate('deny_rate');
const allowRate = new Rate('allow_rate');
const tokenRate = new Rate('token_acquire_rate');

// Token cache — VU başına 1 token, 5dk kullan
let tokenCache = { token: null, exp: 0 };

function getToken() {
  const now = Date.now() / 1000;
  if (tokenCache.token && tokenCache.exp > now + 60) {
    return tokenCache.token;
  }

  const res = http.post(
    `https://${HOST}/auth/realms/${REALM}/protocol/openid-connect/token`,
    {
      grant_type: 'client_credentials',
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
    },
    { tags: { endpoint: 'kc-token' } }
  );

  const ok = res.status === 200;
  tokenRate.add(ok);
  check(res, { 'token 200': (r) => r.status === 200 });

  if (!ok) {
    return null;
  }

  const body = res.json();
  tokenCache = {
    token: body.access_token,
    exp: now + (body.expires_in || 300),
  };
  return tokenCache.token;
}

export default function () {
  // Block 1: Unauthenticated deny probe
  group('deny (no token)', () => {
    const res = http.get(`https://${HOST}/variants`, {
      tags: { endpoint: 'variants-deny' },
    });
    const is401 = res.status === 401;
    denyRate.add(is401);
    check(res, {
      'variants deny 401': (r) => r.status === 401,
      'response has JWT error': (r) => r.body && r.body.includes('JWT'),
    });
  });

  // Block 2: Authenticated allow probe
  group('allow (authenticated)', () => {
    const token = getToken();
    if (!token) {
      allowRate.add(false);
      return;
    }

    const res = http.get(`https://${HOST}/variants`, {
      headers: { Authorization: `Bearer ${token}` },
      tags: { endpoint: 'variants-allow' },
    });
    const is2xx = res.status >= 200 && res.status < 300;
    allowRate.add(is2xx);
    check(res, {
      'variants allow 2xx': (r) => r.status >= 200 && r.status < 300,
    });
  });

  // Block 3: Health edge probe (sentinel)
  group('health sentinel', () => {
    const res = http.get(`https://${HOST}/testai-healthz`, {
      tags: { endpoint: 'sentinel' },
    });
    check(res, { 'sentinel 200': (r) => r.status === 200 });
  });

  // Block 4: Actuator health (authoritative chain)
  group('actuator health', () => {
    const res = http.get(`https://${HOST}/auth/actuator/health`, {
      tags: { endpoint: 'auth-actuator' },
    });
    check(res, { 'actuator 200': (r) => r.status === 200 });
  });

  // Sleep jitter (gerçek trafik pattern)
  sleep(Math.random() * 2 + 0.5);   // 0.5-2.5s
}

// Summary handler (opsiyonel — ASCII + JSON export)
export function handleSummary(data) {
  return {
    'stdout': textSummary(data),
    './k6-zanzibar-load-summary.json': JSON.stringify(data, null, 2),
  };
}

// Simple textSummary (k6 default içerik benzeri)
function textSummary(data) {
  const m = data.metrics;
  return `
=== Zanzibar Load Test Summary ===
Host: ${HOST}
Duration: ${data.state.testRunDurationMs / 1000}s
VUs max: ${data.root_group.checks.length || 'N/A'}

HTTP Requests:
  Total: ${m.http_reqs?.values.count || 0}
  Failed rate: ${(m.http_req_failed?.values.rate * 100 || 0).toFixed(2)}%
  p95 duration: ${m.http_req_duration?.values['p(95)'].toFixed(0)}ms

Authz:
  Deny rate (401): ${(m.deny_rate?.values.rate * 100 || 0).toFixed(2)}%
  Allow rate (2xx): ${(m.allow_rate?.values.rate * 100 || 0).toFixed(2)}%
  Token acquire rate: ${(m.token_acquire_rate?.values.rate * 100 || 0).toFixed(2)}%

Thresholds:
${Object.keys(m).filter(k => m[k].thresholds).map(k => {
  const passed = Object.values(m[k].thresholds).every(t => t.ok);
  return `  ${passed ? '✅' : '❌'} ${k}`;
}).join('\n')}
`;
}
