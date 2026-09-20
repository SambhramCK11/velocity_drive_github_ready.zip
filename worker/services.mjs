/**
 * Service layer — a port of app/services.py.
 *
 * Dates, availability, pricing and bookings. The arithmetic and the validation
 * messages are carried over unchanged, so a price or an error the Worker
 * produces is the one the Flask app would have produced.
 *
 * Dates are handled as plain YYYY-MM-DD strings and converted to day numbers
 * for arithmetic, rather than going through Date objects. A Worker runs in UTC
 * while a renter is in Dubai, and `new Date('2026-09-20')` is midnight UTC —
 * enough to make a same-day pickup look like yesterday. Treating a calendar
 * date as a calendar date sidesteps the whole class of bug.
 */

import { pyRound } from './recommender.mjs';

export const DATE_FMT = 'YYYY-MM-DD';

export const EXTRAS = {
  insurance: { label: 'Full Insurance Waiver', per_day: 75.0, flat: 0.0 },
  chauffeur: { label: 'Professional Chauffeur', per_day: 450.0, flat: 0.0 },
  child_seat: { label: 'Child Seat', per_day: 25.0, flat: 0.0 },
  airport: { label: 'Airport Delivery & Collection', per_day: 0.0, flat: 150.0 },
  extra_driver: { label: 'Additional Driver', per_day: 0.0, flat: 120.0 },
  unlimited_km: { label: 'Unlimited Kilometres', per_day: 60.0, flat: 0.0 },
};

export const BRANCHES = [
  'Dubai Marina',
  'Downtown Dubai',
  'DXB Terminal 3',
  'Business Bay',
  'Jumeirah Beach Road',
];

/** Raised when user input fails a business rule. */
export class ValidationError extends Error {
  constructor(message, field = null) {
    super(message);
    this.name = 'ValidationError';
    this.message_ = message;
    this.field = field;
  }
}

/* ------------------------------------------------------------------ */
/* Dates                                                               */
/* ------------------------------------------------------------------ */

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Validate a YYYY-MM-DD date and return it normalised.
 *
 * Rejects an impossible date rather than letting it roll over the way Date
 * does — '2026-02-31' must not silently become the 3rd of March.
 */
export function parseDate(value, field) {
  const text = String(value ?? '').trim();
  const match = DATE_RE.exec(text);
  if (!match) {
    throw new ValidationError(`'${value}' is not a valid date (expected YYYY-MM-DD).`, field);
  }
  const [, y, m, d] = match.map(Number);
  const probe = new Date(Date.UTC(y, m - 1, d));
  if (
    probe.getUTCFullYear() !== y ||
    probe.getUTCMonth() !== m - 1 ||
    probe.getUTCDate() !== d
  ) {
    throw new ValidationError(`'${value}' is not a valid date (expected YYYY-MM-DD).`, field);
  }
  return text;
}

/** Days since the epoch for a YYYY-MM-DD string. */
export function dayNumber(isoDate) {
  const [y, m, d] = isoDate.split('-').map(Number);
  return Math.floor(Date.UTC(y, m - 1, d) / 86400000);
}

/** Today in Dubai (UTC+4, no daylight saving), as YYYY-MM-DD. */
export function todayInDubai(now = new Date()) {
  return new Date(now.getTime() + 4 * 3600 * 1000).toISOString().slice(0, 10);
}

/** Add days to a YYYY-MM-DD string. */
export function addDays(isoDate, days) {
  return new Date((dayNumber(isoDate) + days) * 86400000).toISOString().slice(0, 10);
}

export function rentalDays(pickup, ret, config) {
  if (dayNumber(ret) <= dayNumber(pickup)) {
    throw new ValidationError('Return date must be after the pickup date.', 'return_date');
  }
  const days = dayNumber(ret) - dayNumber(pickup);
  if (days < config.MIN_RENTAL_DAYS) {
    throw new ValidationError(`Minimum rental is ${config.MIN_RENTAL_DAYS} day(s).`, 'return_date');
  }
  if (days > config.MAX_RENTAL_DAYS) {
    throw new ValidationError(`Maximum rental is ${config.MAX_RENTAL_DAYS} days.`, 'return_date');
  }
  return days;
}

/* ------------------------------------------------------------------ */
/* Rows                                                                */
/* ------------------------------------------------------------------ */

/** A cars row as the rest of the code expects it: features parsed, rate numeric. */
export function rowToCar(row) {
  const car = { ...row };
  try {
    car.features = JSON.parse(row.features || '[]');
  } catch {
    // A malformed features column should not take the page down with it.
    car.features = [];
  }
  car.daily_rate = Number(row.daily_rate);
  car.availability = Math.max(0, Number(row.total_units ?? 1));
  return car;
}

export async function loadFleet(sql, activeOnly = true) {
  const rows = activeOnly
    ? await sql`SELECT * FROM cars WHERE is_active = 1 ORDER BY daily_rate DESC`
    : await sql`SELECT * FROM cars ORDER BY daily_rate DESC`;
  return rows.map(rowToCar);
}

export async function getCar(sql, slug) {
  const rows = await sql`SELECT * FROM cars WHERE slug = ${slug}`;
  return rows.length > 0 ? rowToCar(rows[0]) : null;
}

/* ------------------------------------------------------------------ */
/* Availability                                                        */
/* ------------------------------------------------------------------ */

/**
 * Count confirmed bookings on a car whose window overlaps [pickup, ret).
 *
 * Two ranges overlap when each starts before the other ends — the standard
 * half-open interval test, so a return on the same day a new hire starts is not
 * treated as a clash.
 */
export async function unitsBooked(sql, carId, pickup, ret) {
  const rows = await sql`
    SELECT COUNT(*)::int AS n FROM bookings
    WHERE car_id = ${carId} AND status = 'confirmed'
      AND pickup_date < ${ret} AND return_date > ${pickup}
  `;
  return rows.length > 0 ? Number(rows[0].n) : 0;
}

export async function isAvailable(sql, car, pickup, ret) {
  const taken = await unitsBooked(sql, car.id, pickup, ret);
  const remaining = Math.max(0, Number(car.total_units) - taken);
  return { available: remaining > 0, remaining };
}

/**
 * The cars free across a window, each carrying its remaining unit count.
 *
 * One query counts overlaps for the whole fleet rather than one per car: the
 * Python issues N queries against local SQLite, which is free, but each one
 * here is an HTTPS round trip to Neon.
 */
export async function availableFleet(sql, pickup, ret, cars = null) {
  const fleet = cars ?? (await loadFleet(sql));
  const rows = await sql`
    SELECT car_id, COUNT(*)::int AS n FROM bookings
    WHERE status = 'confirmed'
      AND pickup_date < ${ret} AND return_date > ${pickup}
    GROUP BY car_id
  `;
  const taken = new Map(rows.map((r) => [Number(r.car_id), Number(r.n)]));

  const out = [];
  for (const car of fleet) {
    const remaining = Math.max(0, Number(car.total_units) - (taken.get(Number(car.id)) ?? 0));
    if (remaining > 0) out.push({ ...car, availability: remaining });
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Pricing                                                             */
/* ------------------------------------------------------------------ */

export function discountFor(days, config) {
  for (const [threshold, pct] of config.DISCOUNT_TIERS) {
    if (days >= threshold) return pct;
  }
  return 0.0;
}

export function buildQuote(car, days, extraKeys, config) {
  const chosenKeys = (extraKeys ?? []).filter((key) => key in EXTRAS);

  const baseTotal = car.daily_rate * days;
  const pct = discountFor(days, config);
  const discount = baseTotal * pct;

  const chosen = [];
  let extrasTotal = 0.0;
  for (const key of chosenKeys) {
    const spec = EXTRAS[key];
    const cost = spec.per_day * days + spec.flat;
    extrasTotal += cost;
    chosen.push({ key, label: spec.label, cost: pyRound(cost, 2) });
  }

  const subtotal = baseTotal - discount + extrasTotal;
  const vat = subtotal * config.VAT_RATE;

  return {
    days,
    daily_rate: car.daily_rate,
    base_total: baseTotal,
    discount,
    discount_pct: pct,
    extras_total: extrasTotal,
    extras: chosen,
    subtotal,
    vat,
    total: subtotal + vat,
    deposit: Number(car.deposit || config.SECURITY_DEPOSIT),
    currency: config.CURRENCY,
  };
}

/** The API/template shape: rounded to the decimals a price is quoted in. */
export function quoteToDict(quote) {
  return {
    days: quote.days,
    daily_rate: pyRound(quote.daily_rate, 2),
    base_total: pyRound(quote.base_total, 2),
    discount: pyRound(quote.discount, 2),
    discount_pct: pyRound(quote.discount_pct * 100),
    extras: quote.extras,
    extras_total: pyRound(quote.extras_total, 2),
    subtotal: pyRound(quote.subtotal, 2),
    vat: pyRound(quote.vat, 2),
    total: pyRound(quote.total, 2),
    deposit: pyRound(quote.deposit, 2),
    currency: quote.currency,
  };
}

/* ------------------------------------------------------------------ */
/* Bookings                                                            */
/* ------------------------------------------------------------------ */

/** VD- plus three random bytes, as secrets.token_hex(3).upper() gives. */
export function bookingReference() {
  const bytes = crypto.getRandomValues(new Uint8Array(3));
  return `VD-${[...bytes].map((b) => b.toString(16).padStart(2, '0')).join('').toUpperCase()}`;
}

const REQUIRED_FIELDS = [
  'car_slug',
  'pickup_date',
  'return_date',
  'full_name',
  'email',
  'phone',
];

/** Validate, price and persist a booking. Throws ValidationError. */
export async function createBooking(sql, payload, config) {
  for (const field of REQUIRED_FIELDS) {
    if (!String(payload[field] ?? '').trim()) {
      throw new ValidationError(`'${field.replace(/_/g, ' ')}' is required.`, field);
    }
  }

  const email = String(payload.email).trim();
  if (!email.includes('@') || !email.split('@').pop().includes('.')) {
    throw new ValidationError('Please enter a valid email address.', 'email');
  }

  const car = await getCar(sql, String(payload.car_slug).trim());
  if (car === null) {
    throw new ValidationError('That vehicle is not in our fleet.', 'car_slug');
  }

  const pickup = parseDate(payload.pickup_date, 'pickup_date');
  const ret = parseDate(payload.return_date, 'return_date');
  const days = rentalDays(pickup, ret, config);

  if (dayNumber(pickup) < dayNumber(todayInDubai())) {
    throw new ValidationError('Pickup date cannot be in the past.', 'pickup_date');
  }

  const { available, remaining } = await isAvailable(sql, car, pickup, ret);
  if (!available) {
    throw new ValidationError(
      `All ${car.total_units} unit(s) of the ${car.make} ${car.model} are booked for those dates.`,
      'pickup_date'
    );
  }

  const branch = String(payload.pickup_branch || BRANCHES[0]);
  if (!BRANCHES.includes(branch)) {
    throw new ValidationError('Unknown pickup branch.', 'pickup_branch');
  }

  let extras = payload.extras ?? [];
  if (typeof extras === 'string') extras = extras.split(',').filter(Boolean);
  const quote = buildQuote(car, days, extras, config);

  const [customer] = await sql`
    INSERT INTO customers (full_name, email, phone, licence_no)
    VALUES (${String(payload.full_name).trim()}, ${email},
            ${String(payload.phone).trim()}, ${String(payload.licence_no ?? '').trim()})
    RETURNING id
  `;

  const reference = bookingReference();
  const [booking] = await sql`
    INSERT INTO bookings (
      reference, car_id, customer_id, pickup_date, return_date,
      pickup_branch, days, base_total, discount, extras_total, vat,
      total, extras, status
    ) VALUES (
      ${reference}, ${car.id}, ${customer.id}, ${pickup}, ${ret},
      ${branch}, ${days}, ${quote.base_total}, ${quote.discount},
      ${quote.extras_total}, ${quote.vat}, ${quote.total},
      ${JSON.stringify(quote.extras.map((e) => e.key))}, 'confirmed'
    )
    RETURNING id
  `;

  await sql`UPDATE cars SET rental_count = rental_count + 1 WHERE id = ${car.id}`;

  return {
    id: booking.id,
    reference,
    car,
    pickup_date: pickup,
    return_date: ret,
    pickup_branch: branch,
    customer: { full_name: payload.full_name, email, phone: payload.phone },
    quote: quoteToDict(quote),
    units_remaining: remaining - 1,
    status: 'confirmed',
  };
}

const isoDate = (value) =>
  value instanceof Date ? value.toISOString().slice(0, 10) : String(value).slice(0, 10);

export async function getBooking(sql, reference) {
  const rows = await sql`
    SELECT b.*, c.slug, c.make, c.model, c.year, c.category, c.accent_hex,
           c.art_style, c.daily_rate, cu.full_name, cu.email, cu.phone
    FROM bookings b
    JOIN cars c       ON c.id = b.car_id
    JOIN customers cu ON cu.id = b.customer_id
    WHERE b.reference = ${String(reference).trim().toUpperCase()}
  `;
  if (rows.length === 0) return null;

  const data = { ...rows[0] };
  data.pickup_date = isoDate(data.pickup_date);
  data.return_date = isoDate(data.return_date);
  let keys = [];
  try {
    keys = JSON.parse(data.extras || '[]');
  } catch {
    keys = [];
  }
  data.extras = keys.filter((k) => k in EXTRAS).map((k) => ({ key: k, label: EXTRAS[k].label }));
  return data;
}

export async function cancelBooking(sql, reference) {
  const booking = await getBooking(sql, reference);
  if (booking === null || booking.status === 'cancelled') return false;
  await sql`
    UPDATE bookings SET status = 'cancelled'
    WHERE reference = ${String(reference).trim().toUpperCase()}
  `;
  return true;
}

/** Record a search so ranking can be reviewed later. Best-effort. */
export async function logSearch(sql, queryText, payload, topSlug) {
  try {
    await sql`
      INSERT INTO search_events (query, payload, top_slug)
      VALUES (${String(queryText).slice(0, 500)},
              ${JSON.stringify(payload).slice(0, 2000)}, ${topSlug})
    `;
  } catch (error) {
    // Analytics must never fail a request that otherwise succeeded.
    console.error('log_search failed:', error?.message ?? error);
  }
}
