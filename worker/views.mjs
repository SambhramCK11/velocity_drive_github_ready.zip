/**
 * Template registry and the render helper.
 *
 * The .html files are pulled in as text modules — Wrangler's default module
 * rules treat **\/*.html as Text — and bundled into the Worker, so rendering
 * needs no filesystem. They are the same files Flask renders from
 * app/templates/.
 */

import { CONFIG } from './config.mjs';
import { Environment } from './template.mjs';
import { BRANCHES, addDays, todayInDubai } from './services.mjs';

import base from '../app/templates/base.html';
import card from '../app/templates/_card.html';
import book from '../app/templates/book.html';
import carDetail from '../app/templates/car_detail.html';
import concierge from '../app/templates/concierge.html';
import confirmation from '../app/templates/confirmation.html';
import errorPage from '../app/templates/error.html';
import fleet from '../app/templates/fleet.html';
import index from '../app/templates/index.html';
import lookup from '../app/templates/lookup.html';

const env = new Environment({
  'base.html': base,
  '_card.html': card,
  'book.html': book,
  'car_detail.html': carDetail,
  'concierge.html': concierge,
  'confirmation.html': confirmation,
  'error.html': errorPage,
  'fleet.html': fleet,
  'index.html': index,
  'lookup.html': lookup,
});

/**
 * The globals routes.py injects through its context processor, plus the
 * `request` and `url_for` Flask supplies.
 *
 * `today` and `default_return` are computed in Dubai's timezone: a Worker runs
 * in UTC, and after 20:00 UTC the date a renter sees would otherwise be
 * yesterday's.
 */
export function baseContext(request, endpoint) {
  const url = new URL(request.url);
  const today = todayInDubai();
  const args = Object.fromEntries(url.searchParams.entries());

  return {
    COMPANY: CONFIG.COMPANY_NAME,
    CITY: CONFIG.COMPANY_CITY,
    CURRENCY: CONFIG.CURRENCY,
    BRANCHES,
    today,
    default_return: addDays(today, 3),
    current_year: Number(today.slice(0, 4)),
    url_for: (name, kwargs = {}) => `/static/${kwargs.filename ?? ''}`,
    request: {
      endpoint,
      args: {
        ...args,
        get: (key, fallback = null) => (key in args ? args[key] : fallback),
      },
    },
  };
}

/** Render a template to an HTML Response, as Flask's render_template would. */
export function renderPage(name, context, status = 200) {
  return new Response(env.render(name, context), {
    status,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}

export { env };
