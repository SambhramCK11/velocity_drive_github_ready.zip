/**
 * Cloudflare Worker — Velocity Drive.
 *
 * Serves the seven server-rendered pages from app/routes.py and the twelve
 * /api/v1 endpoints from app/api.py, against Neon Postgres, rendering the same
 * templates Flask renders. The ranking, pricing and validation all come from the
 * ported modules, which are checked against the Python by the test suite.
 *
 * Budget note: the Workers free plan allows 10 ms of CPU per request. Building
 * the TF-IDF index over the eighteen-car fleet is the only expensive step, so it
 * is built once per isolate and reused, and only the two routes that actually
 * rank (the concierge API and a car's "similar" list) touch it at all.
 */

import { CONFIG } from './config.mjs';
import { connect } from './db.mjs';
import { CarRecommender, parseIntent } from './recommender.mjs';
import {
  BRANCHES,
  EXTRAS,
  ValidationError,
  availableFleet,
  buildQuote,
  cancelBooking,
  createBooking,
  getBooking,
  getCar,
  isAvailable,
  loadFleet,
  logSearch,
  parseDate,
  quoteToDict,
  rentalDays,
} from './services.mjs';
import { baseContext, renderPage } from './views.mjs';

/* ------------------------------------------------------------------ */
/* Responses                                                           */
/* ------------------------------------------------------------------ */

const json = (body, status = 200) =>
  new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'access-control-allow-origin': '*',
    },
  });

const redirect = (location) => new Response(null, { status: 302, headers: { location } });

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const notFoundJson = (field) => json({ error: 'not_found', field }, 404);

/* ------------------------------------------------------------------ */
/* Recommender cache                                                   */
/* ------------------------------------------------------------------ */

// One index per isolate. The fleet changes only when someone edits the
// catalogue, and rental_count drifting by a booking or two does not change a
// ranking, so a short TTL is ample and keeps the 18-document index build off
// almost every request.
const INDEX_TTL_MS = 60_000;
let cachedEngine = null;
let cachedAt = 0;

async function engineFor(sql) {
  const now = Date.now();
  if (cachedEngine && now - cachedAt < INDEX_TTL_MS) return cachedEngine;
  cachedEngine = new CarRecommender(await loadFleet(sql), CONFIG.RECOMMENDER_WEIGHTS);
  cachedAt = now;
  return cachedEngine;
}

/* ------------------------------------------------------------------ */
/* Request helpers                                                     */
/* ------------------------------------------------------------------ */

/** A JSON body or a form post, so curl and the browser both work. */
async function payloadOf(request) {
  const type = request.headers.get('content-type') ?? '';
  if (type.includes('application/json')) {
    const data = await request.json().catch(() => null);
    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
      throw new ValidationError('Request body must be a JSON object.');
    }
    return data;
  }
  const form = await request.formData();
  const data = {};
  for (const [key, value] of form.entries()) {
    if (key === 'extras') {
      // Checkboxes repeat the key, as request.form.getlist("extras") collects.
      (data.extras ??= []).push(value);
    } else {
      data[key] = value;
    }
  }
  return data;
}

function numberParam(value, field) {
  if (value === undefined || value === null || value === '') return null;
  const n = Number(value);
  if (!Number.isFinite(n)) throw new ValidationError(`'${field}' must be a number.`, field);
  return n;
}

/* ------------------------------------------------------------------ */
/* Pages                                                              */
/* ------------------------------------------------------------------ */

async function home({ sql, request }) {
  const fleet = await loadFleet(sql);
  const featured = [...fleet]
    .sort((a, b) => b.rating - a.rating || b.rental_count - a.rental_count)
    .slice(0, 3);
  const popular = [...fleet].sort((a, b) => b.rental_count - a.rental_count).slice(0, 6);
  const rows = await sql`
    SELECT category, COUNT(*)::int AS count, MIN(daily_rate) AS from_rate
    FROM cars WHERE is_active = 1 GROUP BY category ORDER BY from_rate
  `;

  return renderPage('index.html', {
    ...baseContext(request, 'web.home'),
    featured,
    popular,
    categories: rows.map((r) => ({ ...r, from_rate: Number(r.from_rate) })),
    fleet_size: fleet.length,
    total_units: fleet.reduce((sum, car) => sum + Number(car.total_units), 0),
  });
}

async function fleetPage({ sql, request }) {
  const cars = await loadFleet(sql);
  const rows = await sql`
    SELECT DISTINCT category FROM cars WHERE is_active = 1 ORDER BY category
  `;
  return renderPage('fleet.html', {
    ...baseContext(request, 'web.fleet'),
    cars,
    categories: rows.map((r) => r.category),
    max_rate: cars.length > 0 ? Math.max(...cars.map((c) => c.daily_rate)) : 5000,
  });
}

async function carDetail({ sql, request, slug }) {
  const car = await getCar(sql, slug);
  if (car === null) throw new HttpError(404, 'No such vehicle');

  const engine = await engineFor(sql);
  const similarSlugs = engine.index
    .search(CarRecommender.profileText(car), 4)
    .map(([s]) => s)
    .filter((s) => s !== slug)
    .slice(0, 3);
  const similar = await Promise.all(similarSlugs.map((s) => getCar(sql, s)));

  return renderPage('car_detail.html', {
    ...baseContext(request, 'web.car_detail'),
    car,
    similar,
    sample_quote: quoteToDict(buildQuote(car, 3, [], CONFIG)),
  });
}

function conciergePage({ request }) {
  return renderPage('concierge.html', {
    ...baseContext(request, 'web.concierge'),
    examples: [
      'Something fast and flashy for my birthday, budget around 3000 a day',
      'Family of six going to the desert for a week',
      'Executive car for airport transfers and client meetings',
      'Cheapest automatic I can rent for a month',
      'Open top convertible for a weekend along the coast',
      'Electric car, low running cost, 5 seats',
    ],
  });
}

async function bookPage({ sql, request, slug }) {
  const car = await getCar(sql, slug);
  if (car === null) throw new HttpError(404, 'No such vehicle');
  const globals = baseContext(request, 'web.book');

  if (request.method === 'POST') {
    const payload = await payloadOf(request);
    payload.car_slug = slug;
    try {
      const booking = await createBooking(sql, payload, CONFIG);
      return redirect(`/booking/${booking.reference}`);
    } catch (error) {
      if (!(error instanceof ValidationError)) throw error;
      // Re-render with the submitted values, as the Flask view does, so the
      // customer does not have to retype the form.
      return renderPage(
        'book.html',
        {
          ...globals,
          car,
          extras: EXTRAS,
          error: error.message,
          field: error.field,
          form: payload,
        },
        400
      );
    }
  }

  return renderPage('book.html', {
    ...globals,
    car,
    extras: EXTRAS,
    error: null,
    field: null,
    form: {
      pickup_date: globals.request.args.get('pickup_date', globals.today),
      return_date: globals.request.args.get('return_date', globals.default_return),
    },
  });
}

async function confirmationPage({ sql, request, slug: reference }) {
  const booking = await getBooking(sql, reference);
  if (booking === null) throw new HttpError(404, 'No such booking');
  return renderPage('confirmation.html', {
    ...baseContext(request, 'web.confirmation'),
    b: booking,
  });
}

async function lookupPage({ sql, request }) {
  const url = new URL(request.url);
  const reference = (url.searchParams.get('reference') ?? '').trim();
  const booking = reference ? await getBooking(sql, reference) : null;
  return renderPage('lookup.html', {
    ...baseContext(request, 'web.lookup'),
    booking,
    reference,
    searched: Boolean(reference),
  });
}

/* ------------------------------------------------------------------ */
/* API — /api/v1                                                       */
/* ------------------------------------------------------------------ */

// How /cars sorts. "recommended" is the fleet's own order, so it re-sorts nothing.
const SORTERS = {
  recommended: null,
  price_asc: (a, b) => a.daily_rate - b.daily_rate,
  price_desc: (a, b) => b.daily_rate - a.daily_rate,
  rating: (a, b) => b.rating - a.rating,
  power: (a, b) => b.horsepower - a.horsepower,
  fastest: (a, b) => a.zero_to_hundred - b.zero_to_hundred,
  popular: (a, b) => b.rental_count - a.rental_count,
};

async function apiHealth({ sql }) {
  const fleet = await loadFleet(sql);
  return json({
    status: 'ok',
    environment: 'workers',
    company: CONFIG.COMPANY_NAME,
    currency: CONFIG.CURRENCY,
    fleet_size: fleet.length,
    total_units: fleet.reduce((sum, car) => sum + Number(car.total_units), 0),
  });
}

async function apiCars({ sql, request }) {
  const url = new URL(request.url);
  let results = await loadFleet(sql);

  const category = url.searchParams.get('category');
  if (category && category !== 'all') results = results.filter((c) => c.category === category);

  const maxPrice = numberParam(url.searchParams.get('max_price'), 'max_price');
  if (maxPrice !== null) results = results.filter((c) => c.daily_rate <= maxPrice);

  const minSeats = numberParam(url.searchParams.get('min_seats'), 'min_seats');
  if (minSeats) results = results.filter((c) => c.seats >= minSeats);

  for (const field of ['fuel_type', 'transmission', 'body_style']) {
    const wanted = url.searchParams.get(field);
    if (wanted && wanted !== 'all') results = results.filter((c) => c[field] === wanted);
  }

  const query = (url.searchParams.get('q') ?? '').trim();
  if (query) {
    // Substring match over the fields a person would type, not the TF-IDF
    // index: this is the fleet filter, and someone typing "bmw" expects the BMWs.
    const needle = query.toLowerCase();
    results = results.filter((c) =>
      `${c.make} ${c.model} ${c.category} ${c.body_style}`.toLowerCase().includes(needle)
    );
  }

  const sort = url.searchParams.get('sort') ?? 'recommended';
  if (!(sort in SORTERS)) throw new ValidationError(`Unknown sort '${sort}'.`, 'sort');
  if (SORTERS[sort]) results = [...results].sort(SORTERS[sort]);

  return json({ cars: results, count: results.length });
}

async function apiCarDetail({ sql, slug }) {
  const car = await getCar(sql, slug);
  if (car === null) return notFoundJson('slug');

  const engine = await engineFor(sql);
  const similarSlugs = engine.index
    .search(CarRecommender.profileText(car), 4)
    .map(([s]) => s)
    .filter((s) => s !== slug)
    .slice(0, 3);
  car.similar = await Promise.all(similarSlugs.map((s) => getCar(sql, s)));

  return json({ car, sample_quote: quoteToDict(buildQuote(car, 3, [], CONFIG)) });
}

async function apiCategories({ sql }) {
  const rows = await sql`
    SELECT category, COUNT(*)::int AS count, MIN(daily_rate) AS from_rate
    FROM cars WHERE is_active = 1 GROUP BY category ORDER BY from_rate
  `;
  return json({ categories: rows.map((r) => ({ ...r, from_rate: Number(r.from_rate) })) });
}

function apiExtras() {
  return json({
    extras: Object.entries(EXTRAS).map(([key, spec]) => ({ key, ...spec })),
    branches: BRANCHES,
    deposit: CONFIG.SECURITY_DEPOSIT,
    vat_rate: CONFIG.VAT_RATE,
  });
}

async function apiAvailability({ sql, request }) {
  const url = new URL(request.url);
  const pickup = parseDate(url.searchParams.get('pickup_date') ?? '', 'pickup_date');
  const ret = parseDate(url.searchParams.get('return_date') ?? '', 'return_date');
  const days = rentalDays(pickup, ret, CONFIG);
  const free = await availableFleet(sql, pickup, ret);
  return json({
    pickup_date: pickup,
    return_date: ret,
    days,
    cars: free,
    count: free.length,
  });
}

async function apiRecommend({ sql, request }) {
  const data = await payloadOf(request);
  const queryText = String(data.query ?? '').trim();

  const overrides = {};
  for (const field of ['budget_max', 'passengers', 'days']) {
    const value = numberParam(data[field], field);
    if (value !== null) overrides[field] = value;
  }

  if (!queryText && Object.keys(overrides).length === 0) {
    throw new ValidationError(
      'Describe what you need, or set a budget or passenger count.',
      'query'
    );
  }

  const intent = parseIntent(queryText, overrides);

  // Dates are optional; when both are given, rank only what is actually free.
  let availableSlugs = null;
  if (data.pickup_date && data.return_date) {
    const pickup = parseDate(String(data.pickup_date), 'pickup_date');
    const ret = parseDate(String(data.return_date), 'return_date');
    rentalDays(pickup, ret, CONFIG);
    availableSlugs = new Set((await availableFleet(sql, pickup, ret)).map((c) => c.slug));
  }

  const limit = Math.max(1, Math.min(Number.parseInt(data.limit ?? 6, 10) || 6, 24));
  const engine = await engineFor(sql);
  const results = engine.recommend(intent, limit, availableSlugs).map((s) => s.toJSON());

  await logSearch(sql, queryText, data, results.length > 0 ? results[0].slug : '');

  return json({ intent: intent.toJSON(), results, count: results.length });
}

async function apiQuote({ sql, request }) {
  const data = await payloadOf(request);
  const car = await getCar(sql, String(data.car_slug ?? '').trim());
  if (car === null) throw new ValidationError('That vehicle is not in our fleet.', 'car_slug');

  let extras = data.extras ?? [];
  if (typeof extras === 'string') extras = [extras];

  // Either a date window or a bare day count: the booking form sends dates,
  // while a price check before any dates are chosen sends days.
  let days;
  let available = true;
  let remaining = Number(car.total_units);

  if (data.pickup_date && data.return_date) {
    const pickup = parseDate(String(data.pickup_date), 'pickup_date');
    const ret = parseDate(String(data.return_date), 'return_date');
    days = rentalDays(pickup, ret, CONFIG);
    ({ available, remaining } = await isAvailable(sql, car, pickup, ret));
  } else if (data.days !== undefined && data.days !== null && data.days !== '') {
    days = Number.parseInt(data.days, 10);
    if (!Number.isInteger(days)) {
      throw new ValidationError("'days' must be a whole number.", 'days');
    }
    if (days < CONFIG.MIN_RENTAL_DAYS || days > CONFIG.MAX_RENTAL_DAYS) {
      throw new ValidationError(
        `Rental length must be between ${CONFIG.MIN_RENTAL_DAYS} and ${CONFIG.MAX_RENTAL_DAYS} days.`,
        'days'
      );
    }
  } else {
    throw new ValidationError(
      'Provide either pickup_date and return_date, or days.',
      'pickup_date'
    );
  }

  return json({
    quote: quoteToDict(buildQuote(car, days, extras, CONFIG)),
    available,
    units_remaining: remaining,
  });
}

async function apiCreateBooking({ sql, request }) {
  const data = await payloadOf(request);
  if (typeof data.extras === 'string') data.extras = [data.extras];
  return json({ booking: await createBooking(sql, data, CONFIG) }, 201);
}

async function apiReadBooking({ sql, slug: reference }) {
  const booking = await getBooking(sql, reference);
  if (booking === null) return notFoundJson('reference');
  return json({ booking });
}

async function apiCancelBooking({ sql, slug: reference }) {
  if (!(await cancelBooking(sql, reference))) {
    return json(
      { error: 'not_found', field: 'reference' },
      404
    );
  }
  return json({ cancelled: true, reference: String(reference).trim().toUpperCase() });
}

async function apiStats({ sql }) {
  const fleet = await loadFleet(sql);
  const [totals] = await sql`
    SELECT COUNT(*)::int                                              AS bookings,
           COALESCE(SUM(total), 0)                                    AS revenue,
           COALESCE(AVG(days), 0)                                     AS avg_days,
           COALESCE(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END), 0)::int AS cancelled
    FROM bookings
  `;
  const categories = await sql`
    SELECT c.category, COUNT(b.id)::int AS bookings, COALESCE(SUM(b.total), 0) AS revenue
    FROM cars c
    LEFT JOIN bookings b ON b.car_id = c.id AND b.status != 'cancelled'
    GROUP BY c.category
    ORDER BY revenue DESC
  `;

  return json({
    fleet_size: fleet.length,
    total_units: fleet.reduce((sum, car) => sum + Number(car.total_units), 0),
    average_daily_rate:
      fleet.length > 0
        ? Math.round((fleet.reduce((s, c) => s + c.daily_rate, 0) / fleet.length) * 100) / 100
        : 0,
    bookings: {
      bookings: Number(totals.bookings),
      revenue: Number(totals.revenue),
      avg_days: Number(totals.avg_days),
      cancelled: Number(totals.cancelled),
    },
    categories: categories.map((r) => ({ ...r, revenue: Number(r.revenue) })),
    currency: CONFIG.CURRENCY,
  });
}

/* ------------------------------------------------------------------ */
/* Route table                                                        */
/* ------------------------------------------------------------------ */

// [methods, pattern, handler]. The first capture group becomes `slug`.
export const ROUTES = [
  // Pages
  [['GET'], /^\/$/, home],
  [['GET'], /^\/fleet$/, fleetPage],
  [['GET'], /^\/cars\/([^/]+)$/, carDetail],
  [['GET'], /^\/concierge$/, conciergePage],
  [['GET', 'POST'], /^\/book\/([^/]+)$/, bookPage],
  [['GET'], /^\/booking\/([^/]+)$/, confirmationPage],
  [['GET'], /^\/lookup$/, lookupPage],

  // API
  [['GET'], /^\/api\/v1\/health$/, apiHealth],
  [['GET'], /^\/api\/v1\/cars$/, apiCars],
  [['GET'], /^\/api\/v1\/cars\/([^/]+)$/, apiCarDetail],
  [['GET'], /^\/api\/v1\/categories$/, apiCategories],
  [['GET'], /^\/api\/v1\/extras$/, apiExtras],
  [['GET'], /^\/api\/v1\/availability$/, apiAvailability],
  [['POST'], /^\/api\/v1\/recommend$/, apiRecommend],
  [['POST'], /^\/api\/v1\/quote$/, apiQuote],
  [['POST'], /^\/api\/v1\/bookings$/, apiCreateBooking],
  [['GET'], /^\/api\/v1\/bookings\/([^/]+)$/, apiReadBooking],
  [['POST'], /^\/api\/v1\/bookings\/([^/]+)\/cancel$/, apiCancelBooking],
  [['GET'], /^\/api\/v1\/stats$/, apiStats],
];

/* ------------------------------------------------------------------ */
/* Entry point                                                        */
/* ------------------------------------------------------------------ */

/**
 * The request pipeline.
 *
 * `makeSql` is injected so tests can drive a handler against a stub client
 * instead of a database; production calls it with connect().
 */
export async function handle(request, env, makeSql = connect) {
  const url = new URL(request.url);
  const isApi = url.pathname.startsWith('/api/');

  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'access-control-allow-origin': '*',
        'access-control-allow-methods': 'GET, POST, OPTIONS',
        'access-control-allow-headers': 'content-type',
      },
    });
  }

  if (url.pathname.startsWith('/static/')) {
    return env.ASSETS ? env.ASSETS.fetch(request) : new Response('Not found', { status: 404 });
  }

  let pathMatched = false;
  for (const [methods, pattern, handler] of ROUTES) {
    const match = pattern.exec(url.pathname);
    if (!match) continue;
    pathMatched = true;
    if (!methods.includes(request.method)) continue;

    try {
      if (!env.DATABASE_URL) {
        throw new HttpError(
          503,
          'DATABASE_URL is not configured. Set it with: npx wrangler secret put DATABASE_URL'
        );
      }
      return await handler({
        sql: makeSql(env.DATABASE_URL),
        request,
        env,
        slug: match[1] !== undefined ? decodeURIComponent(match[1]) : undefined,
      });
    } catch (error) {
      return errorResponse(error, request, isApi);
    }
  }

  if (pathMatched) {
    return isApi
      ? json({ error: 'method_not_allowed' }, 405)
      : new Response('Method not allowed', { status: 405 });
  }
  return isApi
    ? notFoundJson(null)
    : renderPage(
        'error.html',
        { ...baseContext(request, 'web.home'), code: 404, message: 'Page not found' },
        404
      );
}

export default {
  fetch: (request, env) => handle(request, env),
};

/** Map a thrown error onto a response, JSON or HTML depending on the surface. */
function errorResponse(error, request, isApi) {
  if (error instanceof ValidationError) {
    return isApi
      ? json({ error: error.message, field: error.field }, 400)
      : renderPage(
          'error.html',
          { ...baseContext(request, 'web.home'), code: 400, message: error.message },
          400
        );
  }
  if (error instanceof HttpError) {
    if (isApi) return json({ error: error.message }, error.status);
    return renderPage(
      'error.html',
      { ...baseContext(request, 'web.home'), code: error.status, message: error.message },
      error.status
    );
  }

  console.error('Unhandled error:', error?.stack ?? error);
  return isApi
    ? json({ error: 'internal_error' }, 500)
    : renderPage(
        'error.html',
        { ...baseContext(request, 'web.home'), code: 500, message: 'Something went wrong' },
        500
      );
}
