/**
 * Differential test: worker/recommender.mjs against app/recommender.py.
 *
 * A ranking that quietly disagrees with the Flask app's would be invisible
 * until someone compared two pages side by side, so every intent field, every
 * signal, every score and every reason string is compared against fixtures
 * generated from the Python by scripts/export-recommender-fixtures.py.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { CarRecommender, parseIntent, pyFloat, pyRound } from '../worker/recommender.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(resolve(here, 'recommender-fixtures.json'), 'utf8'));

const engine = new CarRecommender(fixtures.cars, fixtures.weights);
const close = (a, b, tolerance = 1e-12) => Math.abs(a - b) < tolerance;

test('profile text matches the Python', () => {
  for (const [slug, expected] of Object.entries(fixtures.profile_text)) {
    const car = fixtures.cars.find((c) => c.slug === slug);
    assert.equal(CarRecommender.profileText(car), expected, slug);
  }
});

test('parseIntent matches the Python on every query', () => {
  for (const [query, expected] of Object.entries(fixtures.intents)) {
    assert.deepEqual(
      JSON.parse(JSON.stringify(parseIntent(query))),
      expected,
      `parseIntent(${JSON.stringify(query)})`
    );
  }
});

test('explicit overrides win over inference, as in the Python', () => {
  for (const { query, overrides, intent } of fixtures.intents_with_overrides) {
    assert.deepEqual(
      JSON.parse(JSON.stringify(parseIntent(query, overrides))),
      intent,
      `${query} + ${JSON.stringify(overrides)}`
    );
  }
});

test('"heading to the desert" is not read as a supercar request', () => {
  // The word-boundary rule in cueHit exists for exactly this: plain substring
  // matching found "head" in "heading" and voted Supercar.
  const intent = parseIntent('heading to the desert');
  assert.deepEqual(intent.categories, ['SUV']);
  assert.ok(!intent.categories.includes('Supercar'));
});

test('a soft budget is not strict, a hard one is', () => {
  assert.equal(parseIntent('around 3000').budget_strict, false);
  assert.equal(parseIntent('under 3000').budget_strict, true);
  assert.equal(parseIntent('under 3k').budget_max, 3000);
});

test('rankings match the Python: order, scores, signals and reasons', () => {
  for (const [query, expected] of Object.entries(fixtures.rankings)) {
    const actual = engine.recommend(parseIntent(query), 6);
    assert.equal(actual.length, expected.length, `result count for ${JSON.stringify(query)}`);

    assert.deepEqual(
      actual.map((s) => s.car.slug),
      expected.map((e) => e.slug),
      `order for ${JSON.stringify(query)}`
    );

    for (const [i, scored] of actual.entries()) {
      const want = expected[i];
      assert.ok(
        close(scored.score, want.score),
        `score[${i}] for ${JSON.stringify(query)}: ${scored.score} !== ${want.score}`
      );
      for (const [name, value] of Object.entries(scored.signals)) {
        assert.ok(
          close(value, want.signals[name]),
          `signal ${name}[${i}] for ${JSON.stringify(query)}: ${value} !== ${want.signals[name]}`
        );
      }
      assert.deepEqual(
        scored.reasons,
        want.reasons,
        `reasons[${i}] for ${JSON.stringify(query)}`
      );
    }
  }
});

test('the reported percent and rounded score match the Python', () => {
  for (const [query, expected] of Object.entries(fixtures.rankings)) {
    const actual = engine.recommend(parseIntent(query), 6);
    for (const [i, scored] of actual.entries()) {
      const payload = scored.toJSON();
      assert.equal(
        payload.match.percent,
        expected[i].percent,
        `percent[${i}] for ${JSON.stringify(query)}`
      );
      assert.ok(
        close(payload.match.score, expected[i].rounded_score, 1e-9),
        `rounded score[${i}] for ${JSON.stringify(query)}`
      );
    }
  }
});

test('pyRound rounds halves to even, as Python does', () => {
  assert.equal(pyRound(0.5), 0);
  assert.equal(pyRound(1.5), 2);
  assert.equal(pyRound(2.5), 2);
  assert.equal(pyRound(3.5), 4);
  // 2.675 is 2.67499… in binary, so this is not a tie and rounds down —
  // the same answer Python gives.
  assert.equal(pyRound(2.675, 2), 2.67);
  assert.equal(pyRound(1.005, 2), 1.0);
  assert.equal(pyRound(0.145, 2), 0.14);
});

test('pyFloat keeps the decimal point Python prints', () => {
  assert.equal(pyFloat(5.0), '5.0');
  assert.equal(pyFloat(4.9), '4.9');
  assert.equal(pyFloat(4.85), '4.85');
});

test('a passenger count filters out cars that are too small', () => {
  const scored = engine.recommend(parseIntent('group of 8 for a team offsite'), 6);
  assert.ok(scored.length > 0);
  assert.ok(scored.every((s) => s.car.seats >= 8), 'every result must seat 8');
});

test('a strict ceiling filters rather than merely penalising', () => {
  const scored = engine.recommend(parseIntent('under 500 aed per day'), 6);
  assert.ok(scored.length > 0);
  assert.ok(
    scored.every((s) => s.car.daily_rate <= 500 * 1.02),
    'a strict budget admits only cars inside the 2% tolerance'
  );
});

test('availableSlugs restricts the candidate set', () => {
  const only = new Set(['nissan-sunny', 'toyota-corolla-hybrid']);
  const scored = engine.recommend(parseIntent('anything'), 6, only);
  assert.deepEqual(new Set(scored.map((s) => s.car.slug)), only);
});
