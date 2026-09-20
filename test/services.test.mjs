/**
 * Differential test: worker/services.mjs pricing against app/services.py.
 *
 * Pricing is the part of this app a customer will check with a calculator, so
 * 240 quotes — four cars across ten durations and six add-on combinations — are
 * compared against fixtures generated from the Python, both the raw floats and
 * the rounded figures the page and the API actually show.
 *
 * The date helpers are tested here too, because they are where the port
 * deliberately differs: the Python leans on Python's `date`, while the Worker
 * treats a calendar date as a string to avoid a UTC midnight turning a
 * same-day pickup into yesterday.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { CONFIG } from '../worker/config.mjs';
import {
  EXTRAS,
  ValidationError,
  addDays,
  buildQuote,
  dayNumber,
  discountFor,
  parseDate,
  quoteToDict,
  rentalDays,
  rowToCar,
  todayInDubai,
} from '../worker/services.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(resolve(here, 'services-fixtures.json'), 'utf8'));

const close = (a, b, tolerance = 1e-9) => Math.abs(a - b) < tolerance;

test('the add-on catalogue matches the Python', () => {
  assert.deepEqual(EXTRAS, fixtures.extras);
});

test('discountFor matches the Python for 0..94 days', () => {
  for (const [days, expected] of Object.entries(fixtures.discount_for)) {
    assert.equal(discountFor(Number(days), CONFIG), expected, `${days} days`);
  }
});

test('every quote matches the Python, raw and rounded', () => {
  for (const testCase of fixtures.cases) {
    const car = fixtures.cars[testCase.slug];
    const quote = buildQuote(car, testCase.days, testCase.extras, CONFIG);
    const label = `${testCase.slug} / ${testCase.days}d / [${testCase.extras}]`;

    for (const [field, expected] of Object.entries(testCase.raw)) {
      assert.ok(
        close(quote[field], expected),
        `${label} raw ${field}: ${quote[field]} !== ${expected}`
      );
    }

    const rounded = quoteToDict(quote);
    for (const [field, expected] of Object.entries(testCase.dict)) {
      if (field === 'extras') {
        assert.deepEqual(rounded.extras, expected, `${label} extras`);
      } else if (typeof expected === 'number') {
        assert.ok(
          close(rounded[field], expected),
          `${label} rounded ${field}: ${rounded[field]} !== ${expected}`
        );
      } else {
        assert.equal(rounded[field], expected, `${label} ${field}`);
      }
    }
  }
});

test('unknown add-ons are dropped rather than priced', () => {
  const car = fixtures.cars['nissan-sunny'];
  const quote = buildQuote(car, 2, ['free_yacht', 'insurance'], CONFIG);
  assert.equal(quote.extras.length, 1);
  assert.equal(quote.extras[0].key, 'insurance');
});

test('VAT applies after the discount and the add-ons', () => {
  const car = fixtures.cars['mercedes-s500'];
  const quote = buildQuote(car, 5, ['insurance', 'chauffeur'], CONFIG);
  const subtotal = quote.base_total - quote.discount + quote.extras_total;
  assert.ok(close(quote.vat, subtotal * CONFIG.VAT_RATE));
  assert.ok(close(quote.total, subtotal + quote.vat));
});

/* ------------------------------------------------------------------ */
/* Dates                                                              */
/* ------------------------------------------------------------------ */

test('parseDate accepts a valid date and returns it normalised', () => {
  assert.equal(parseDate('2026-09-20', 'pickup_date'), '2026-09-20');
  assert.equal(parseDate('  2026-09-20  ', 'pickup_date'), '2026-09-20');
});

test('parseDate rejects malformed and impossible dates', () => {
  for (const bad of ['', 'tomorrow', '20-09-2026', '2026-9-20', '2026-13-01', '2026-02-31']) {
    assert.throws(
      () => parseDate(bad, 'pickup_date'),
      (error) => error instanceof ValidationError && error.field === 'pickup_date',
      `should reject ${JSON.stringify(bad)}`
    );
  }
});

test('dayNumber and addDays do calendar arithmetic across a month end', () => {
  assert.equal(dayNumber('2026-09-21') - dayNumber('2026-09-20'), 1);
  assert.equal(addDays('2026-09-30', 1), '2026-10-01');
  assert.equal(addDays('2026-12-31', 1), '2027-01-01');
  // 2028 is a leap year.
  assert.equal(addDays('2028-02-28', 1), '2028-02-29');
});

test('rentalDays counts nights and enforces the configured bounds', () => {
  assert.equal(rentalDays('2026-09-20', '2026-09-21', CONFIG), 1);
  assert.equal(rentalDays('2026-09-20', '2026-09-30', CONFIG), 10);

  assert.throws(
    () => rentalDays('2026-09-20', '2026-09-20', CONFIG),
    (e) => e instanceof ValidationError && e.field === 'return_date'
  );
  assert.throws(
    () => rentalDays('2026-09-20', '2026-09-19', CONFIG),
    (e) => e instanceof ValidationError && e.field === 'return_date'
  );
  assert.throws(
    () => rentalDays('2026-01-01', '2026-12-31', CONFIG),
    (e) => e instanceof ValidationError && /Maximum rental is 90 days/.test(e.message)
  );
});

test('todayInDubai is the local date, not the UTC one', () => {
  // 22:00 UTC on the 20th is 02:00 on the 21st in Dubai. A Worker running in
  // UTC would otherwise reject a same-day pickup as being in the past.
  assert.equal(todayInDubai(new Date('2026-09-20T22:00:00Z')), '2026-09-21');
  assert.equal(todayInDubai(new Date('2026-09-20T10:00:00Z')), '2026-09-20');
});

/* ------------------------------------------------------------------ */
/* Rows                                                              */
/* ------------------------------------------------------------------ */

test('rowToCar parses the features JSON and coerces the rate', () => {
  const car = rowToCar({
    features: '["Launch Control", "Sport Exhaust"]',
    daily_rate: '3200',
    total_units: 2,
  });
  assert.deepEqual(car.features, ['Launch Control', 'Sport Exhaust']);
  assert.equal(car.daily_rate, 3200);
  assert.equal(car.availability, 2);
});

test('rowToCar survives a malformed features column', () => {
  const car = rowToCar({ features: 'not json', daily_rate: 100, total_units: 1 });
  assert.deepEqual(car.features, []);
});
