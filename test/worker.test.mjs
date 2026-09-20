/**
 * Route parity and request-level tests for the Worker.
 *
 * Parity is checked against Flask's own url_map (test/flask-routes.json), so a
 * page or endpoint dropped in the port fails here instead of 404ing in
 * production. The request tests call the exported fetch() handler directly with
 * a stub env — Node 22 supplies Request/Response and Web Crypto — so routing and
 * error mapping are exercised without booting a runtime or a database.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import worker, { ROUTES, handle } from '../worker/index.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const flaskRoutes = JSON.parse(readFileSync(resolve(here, 'flask-routes.json'), 'utf8'));

/** Turn Flask's /cars/<slug> into a concrete path the Worker can match. */
const concrete = (rule) => rule.replace(/<[^>]+>/g, 'x');

function match(pathname) {
  for (const [methods, pattern] of ROUTES) {
    if (pattern.test(pathname)) return methods;
  }
  return null;
}

const stubAssets = { fetch: () => new Response('asset body', { status: 200 }) };

const call = (path, { method = 'GET', env = { ASSETS: stubAssets }, body, headers } = {}) =>
  worker.fetch(
    new Request(`https://example.workers.dev${path}`, { method, body, headers }),
    env
  );

/* ------------------------------------------------------------------ */
/* Parity                                                             */
/* ------------------------------------------------------------------ */

test('the Worker covers every Flask route', () => {
  const missing = flaskRoutes.filter((r) => match(concrete(r.rule)) === null).map((r) => r.rule);
  assert.deepEqual(missing, [], `present in Flask but not the Worker: ${missing}`);
});

test('each route accepts the same methods as Flask', () => {
  const mismatched = [];
  for (const route of flaskRoutes) {
    const methods = match(concrete(route.rule));
    if (!methods) continue;
    if ([...methods].sort().join(',') !== route.methods.join(',')) {
      mismatched.push(`${route.rule}: flask=${route.methods} worker=${[...methods].sort()}`);
    }
  }
  assert.deepEqual(mismatched, []);
});

test('the Worker adds no routes Flask does not have', () => {
  const flaskPaths = flaskRoutes.map((r) => concrete(r.rule));
  const unused = ROUTES.filter(([, pattern]) => !flaskPaths.some((p) => pattern.test(p))).map(
    ([, pattern]) => String(pattern)
  );
  assert.deepEqual(unused, []);
});

test('a cancel path does not shadow the booking-read path', () => {
  // /api/v1/bookings/VD-1/cancel must be POST-only, and
  // /api/v1/bookings/VD-1 must be GET — the patterns are ordered so the more
  // specific one is not swallowed by the other.
  assert.deepEqual(match('/api/v1/bookings/VD-1'), ['GET']);
  assert.deepEqual(match('/api/v1/bookings/VD-1/cancel'), ['POST']);
});

/* ------------------------------------------------------------------ */
/* Request handling                                                   */
/* ------------------------------------------------------------------ */

test('an unknown page renders the error template', async () => {
  const response = await call('/no-such-page');
  assert.equal(response.status, 404);
  const body = await response.text();
  assert.match(body, /Page not found/);
  assert.match(response.headers.get('content-type'), /text\/html/);
});

test('an unknown API path answers with JSON, not HTML', async () => {
  const response = await call('/api/v1/nope');
  assert.equal(response.status, 404);
  assert.match(response.headers.get('content-type'), /application\/json/);
  assert.deepEqual(await response.json(), { error: 'not_found', field: null });
});

test('a known path with the wrong method is a 405 on both surfaces', async () => {
  const page = await call('/fleet', { method: 'POST' });
  assert.equal(page.status, 405);

  const api = await call('/api/v1/health', { method: 'POST' });
  assert.equal(api.status, 405);
  assert.deepEqual(await api.json(), { error: 'method_not_allowed' });
});

test('a missing DATABASE_URL is reported as a 503, with the fix', async () => {
  const response = await call('/api/v1/health');
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /wrangler secret put DATABASE_URL/);
});

test('a page reports the missing database as HTML', async () => {
  const response = await call('/fleet');
  assert.equal(response.status, 503);
  assert.match(await response.text(), /DATABASE_URL is not configured/);
});

test('/static/* is delegated to the assets binding', async () => {
  const response = await call('/static/css/style.css');
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'asset body');
});

test('a CORS preflight is answered without touching the database', async () => {
  const response = await call('/api/v1/recommend', { method: 'OPTIONS' });
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('access-control-allow-origin'), '*');
  assert.match(response.headers.get('access-control-allow-methods'), /POST/);
});

/* ------------------------------------------------------------------ */
/* Handlers against a stub database                                   */
/* ------------------------------------------------------------------ */

/** One row of the cars table, shaped as Postgres returns it. */
const CAR = {
  id: 1,
  slug: 'nissan-sunny',
  make: 'Nissan',
  model: 'Sunny',
  year: 2024,
  category: 'Economy',
  body_style: 'Sedan',
  transmission: 'Automatic',
  fuel_type: 'Petrol',
  seats: 5,
  doors: 4,
  luggage: 2,
  horsepower: 99,
  zero_to_hundred: 11.5,
  daily_rate: 99,
  deposit: 700,
  rating: 4.3,
  rental_count: 210,
  total_units: 6,
  color: 'White',
  accent_hex: '#c9a227',
  art_style: 'sedan',
  features: '["Bluetooth"]',
  tagline: 'Cheap and cheerful.',
  description: 'An economical automatic sedan for city driving.',
  is_active: 1,
};

/**
 * A stand-in for the Neon tagged-template client.
 *
 * Matches on a fragment of the SQL text and returns canned rows, which is
 * enough to drive a handler end to end. The Worker takes its client through an
 * injected factory, so no production code knows about this.
 */
function stubSql(routes) {
  const answer = (text) => {
    for (const [needle, rows] of routes) {
      if (text.includes(needle)) return Promise.resolve(rows);
    }
    return Promise.resolve([]);
  };
  const tag = (strings, ...values) =>
    answer(Array.isArray(strings) ? strings.join(' ? ') : String(strings));
  tag.query = (text) => answer(text);
  return tag;
}

const withDb = (routes) => ({
  env: { ASSETS: stubAssets, DATABASE_URL: 'postgres://stub' },
  makeSql: () => stubSql(routes),
});

const callWith = (path, routes, options = {}) => {
  const { env, makeSql } = withDb(routes);
  return handle(
    new Request(`https://example.workers.dev${path}`, {
      method: options.method ?? 'GET',
      body: options.body,
      headers: options.headers,
    }),
    env,
    makeSql
  );
};

test('GET /api/v1/health reports the fleet size', async () => {
  const response = await callWith('/api/v1/health', [['FROM cars', [CAR]]]);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.status, 'ok');
  assert.equal(body.fleet_size, 1);
  assert.equal(body.total_units, 6);
  assert.equal(body.currency, 'AED');
});

test('GET /api/v1/cars filters, searches and sorts', async () => {
  const cheap = { ...CAR, slug: 'cheap', daily_rate: 50, make: 'Kia' };
  const rows = [['FROM cars', [CAR, cheap]]];

  const all = await (await callWith('/api/v1/cars', rows)).json();
  assert.equal(all.count, 2);

  const filtered = await (await callWith('/api/v1/cars?max_price=60', rows)).json();
  assert.deepEqual(filtered.cars.map((c) => c.slug), ['cheap']);

  const searched = await (await callWith('/api/v1/cars?q=nissan', rows)).json();
  assert.deepEqual(searched.cars.map((c) => c.slug), ['nissan-sunny']);

  const sorted = await (await callWith('/api/v1/cars?sort=price_asc', rows)).json();
  assert.deepEqual(sorted.cars.map((c) => c.daily_rate), [50, 99]);
});

test('GET /api/v1/cars rejects an unknown sort with a 400 and the field', async () => {
  const response = await callWith('/api/v1/cars?sort=sideways', [['FROM cars', [CAR]]]);
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { error: "Unknown sort 'sideways'.", field: 'sort' });
});

test('GET /api/v1/cars/<slug> returns not_found for an unknown slug', async () => {
  const response = await callWith('/api/v1/cars/flying-carpet', [['WHERE slug', []]]);
  assert.equal(response.status, 404);
  assert.deepEqual(await response.json(), { error: 'not_found', field: 'slug' });
});

test('POST /api/v1/quote prices a bare day count', async () => {
  const response = await callWith('/api/v1/quote', [['WHERE slug', [CAR]]], {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ car_slug: 'nissan-sunny', days: 3 }),
  });
  assert.equal(response.status, 200);
  const { quote } = await response.json();
  assert.equal(quote.days, 3);
  assert.equal(quote.base_total, 297);
  // Three days earns the 7% tier.
  assert.equal(quote.discount_pct, 7);
});

test('POST /api/v1/quote rejects an unknown car with a 400 naming the field', async () => {
  const response = await callWith('/api/v1/quote', [['WHERE slug', []]], {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ car_slug: 'delorean', days: 2 }),
  });
  assert.equal(response.status, 400);
  assert.equal((await response.json()).field, 'car_slug');
});

test('POST /api/v1/quote requires either dates or days', async () => {
  const response = await callWith('/api/v1/quote', [['WHERE slug', [CAR]]], {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ car_slug: 'nissan-sunny' }),
  });
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /pickup_date and return_date, or days/);
});

test('POST /api/v1/recommend needs a query or a constraint', async () => {
  const response = await callWith('/api/v1/recommend', [['FROM cars', [CAR]]], {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({}),
  });
  assert.equal(response.status, 400);
  assert.equal((await response.json()).field, 'query');
});

test('POST /api/v1/recommend ranks and returns the parsed intent', async () => {
  const response = await callWith('/api/v1/recommend', [['FROM cars', [CAR]]], {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: 'cheap automatic city car', limit: 3 }),
  });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.count, 1);
  assert.deepEqual(body.intent.categories.sort(), ['Compact', 'Economy']);
  assert.ok(body.results[0].match.percent >= 0 && body.results[0].match.percent <= 100);
  assert.ok(Array.isArray(body.results[0].match.reasons));
});

test('GET /api/v1/availability rejects reversed dates', async () => {
  const response = await callWith(
    '/api/v1/availability?pickup_date=2026-10-10&return_date=2026-10-01',
    [['FROM cars', [CAR]]]
  );
  assert.equal(response.status, 400);
  assert.equal((await response.json()).field, 'return_date');
});

test('GET /api/v1/bookings/<ref> returns not_found when there is none', async () => {
  const response = await callWith('/api/v1/bookings/VD-NOPE', [['FROM bookings', []]]);
  assert.equal(response.status, 404);
  assert.deepEqual(await response.json(), { error: 'not_found', field: 'reference' });
});

test('a page renders against the stub, inheriting the shared layout', async () => {
  const response = await callWith('/fleet', [
    ['FROM cars WHERE is_active = 1 ORDER BY daily_rate', [CAR]],
    ['DISTINCT category', [{ category: 'Economy' }]],
  ]);
  assert.equal(response.status, 200);
  const html = await response.text();

  // base.html's shell, supplied through {% extends %}.
  assert.match(html, /<title>Fleet — Velocity Drive<\/title>/);
  assert.match(html, /\/static\/css\/style\.css/);
  // The page's own context: the class list and the price ceiling. The car grid
  // itself is filled in by static/js/fleet.js from /api/v1/cars, so no vehicle
  // names appear in the server-rendered HTML.
  assert.match(html, /<option value="Economy">Economy<\/option>/);
  assert.match(html, /max="99"/);
});

test('an unknown car renders the error page, not a stack trace', async () => {
  const response = await callWith('/cars/flying-carpet', [['WHERE slug', []]]);
  assert.equal(response.status, 404);
  const html = await response.text();
  assert.match(html, /No such vehicle/);
  assert.doesNotMatch(html, /at Object/);
});
