/**
 * Differential test: worker/template.mjs against Jinja2.
 *
 * Every template is rendered by both engines from the same context and compared
 * byte for byte. Sixteen cases cover each page plus the branches that only show
 * up in one state — a booking with a discount and one without, a validation
 * error on the booking form, a cancelled reservation, a reference that matches
 * nothing, and a card with and without a match score.
 *
 * Fixtures come from scripts/export-template-fixtures.py.
 */

import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { Environment, Safe, escapeHtml, truthy } from '../worker/template.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const fixtures = JSON.parse(readFileSync(resolve(here, 'template-fixtures.json'), 'utf8'));

const templateDir = resolve(root, 'app/templates');
const sources = Object.fromEntries(
  readdirSync(templateDir)
    .filter((f) => f.endsWith('.html'))
    .map((f) => [f, readFileSync(resolve(templateDir, f), 'utf8')])
);

const env = new Environment(sources);

/**
 * Rebuild the parts of the context JSON cannot carry: url_for, and request.args
 * with the .get(key, default) the templates call.
 */
function hydrate(context) {
  const args = context.request?.args ?? {};
  return {
    ...context,
    url_for: (endpoint, kwargs = {}) => `/static/${kwargs.filename ?? ''}`,
    request: {
      endpoint: context.request?.endpoint,
      args: {
        ...args,
        get: (key, fallback = null) => (key in args ? args[key] : fallback),
      },
    },
  };
}

test('every template on disk is exercised, directly or as a parent', () => {
  // base.html is never rendered on its own — it is reached through extends, so
  // count a template as covered when a fixture renders it or inherits from it.
  const covered = new Set();
  for (const { template } of Object.values(fixtures.cases)) {
    covered.add(template);
    const extended = /\{%\s*extends\s+["']([^"']+)["']/.exec(sources[template]);
    if (extended) covered.add(extended[1]);
  }
  const missing = Object.keys(sources).filter((name) => !covered.has(name));
  assert.deepEqual(missing, [], `templates never exercised: ${missing}`);
});

for (const [label, { template, context }] of Object.entries(fixtures.cases)) {
  test(`${label} matches Jinja2 byte for byte`, () => {
    const actual = env.render(template, hydrate(context));
    assert.equal(actual, fixtures.expected[label]);
  });
}

/* ------------------------------------------------------------------ */
/* Engine behaviour worth pinning down directly                        */
/* ------------------------------------------------------------------ */

test('escaping uses MarkupSafe\u2019s table, and Safe passes through', () => {
  assert.equal(escapeHtml(`<a href="x">&'`), '&lt;a href=&#34;x&#34;&gt;&amp;&#39;');
  assert.equal(escapeHtml(new Safe('<b>bold</b>')), '<b>bold</b>');
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
});

test('truthiness follows Python, not JavaScript', () => {
  assert.equal(truthy([]), false);
  assert.equal(truthy({}), false);
  assert.equal(truthy(''), false);
  assert.equal(truthy(0), false);
  assert.equal(truthy([0]), true);
  assert.equal(truthy({ a: 1 }), true);
  assert.equal(truthy('0'), true);
});

test('an unsupported tag or filter fails at parse time, not silently', () => {
  const broken = new Environment({ 'x.html': '{% macro thing() %}{% endmacro %}' });
  assert.throws(() => broken.render('x.html', {}), /Unsupported template tag/);

  const badFilter = new Environment({ 'y.html': '{{ x|nosuchfilter }}' });
  assert.throws(() => badFilter.render('y.html', {}), /Unsupported filter/);
});

test('an undefined value renders empty rather than "undefined"', () => {
  const e = new Environment({ 't.html': '[{{ missing }}][{{ a.b.c }}]' });
  assert.equal(e.render('t.html', { a: {} }), '[][]');
});

test('inheritance takes the most derived block', () => {
  const e = new Environment({
    'base.html': '<h1>{% block t %}base{% endblock %}</h1><p>{% block b %}bb{% endblock %}</p>',
    'mid.html': '{% extends "base.html" %}{% block t %}mid{% endblock %}',
    'leaf.html': '{% extends "mid.html" %}{% block b %}leaf{% endblock %}',
  });
  assert.equal(e.render('leaf.html', {}), '<h1>mid</h1><p>leaf</p>');
});

test('loop exposes index, first and last', () => {
  const e = new Environment({
    't.html': '{% for x in items %}{{ loop.index }}{{ x }}{% if loop.first %}F{% endif %}{% if loop.last %}L{% endif %}{% endfor %}',
  });
  assert.equal(e.render('t.html', { items: ['a', 'b'] }), '1aF2bL');
});

test('a for loop over an empty list takes the else branch', () => {
  const e = new Environment({ 't.html': '{% for x in xs %}{{ x }}{% else %}none{% endfor %}' });
  assert.equal(e.render('t.html', { xs: [] }), 'none');
});

test('the money filters group thousands and fix the decimals', () => {
  const e = new Environment({ 't.html': '{{ a|money }}|{{ a|money2 }}|{{ b|money }}' });
  assert.equal(e.render('t.html', { a: 2550.5, b: 99 }), '2,551|2,550.50|99');
});

test('tojson escapes the characters that could break out of a script', () => {
  const e = new Environment({ 't.html': '{{ v|tojson }}' });
  assert.equal(e.render('t.html', { v: '</script>' }), '"\\u003c/script\\u003e"');
});
