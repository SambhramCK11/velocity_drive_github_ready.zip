/* Shared frontend helpers. No framework, no CDN — everything is local. */
(function () {
  'use strict';

  /* ---------- tiny API client ---------- */
  const api = {
    async get(path, params) {
      const url = new URL(path, location.origin);
      Object.entries(params || {}).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) url.searchParams.set(k, v);
      });
      return handle(await fetch(url, { headers: { Accept: 'application/json' } }));
    },
    async post(path, body) {
      return handle(await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body || {})
      }));
    }
  };

  async function handle(res) {
    let data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok) {
      const err = new Error((data && data.message) || `Request failed (${res.status})`);
      err.field = data && data.field;
      err.status = res.status;
      throw err;
    }
    return data;
  }

  /* ---------- formatting ---------- */
  const currency = () => window.VD_CURRENCY || 'AED';

  function money(value, decimals) {
    const n = Number(value) || 0;
    return n.toLocaleString('en-US', {
      minimumFractionDigits: decimals === undefined ? 0 : decimals,
      maximumFractionDigits: decimals === undefined ? 0 : decimals
    });
  }

  function price(value, decimals) {
    return `${currency()} ${money(value, decimals)}`;
  }

  function daysBetween(a, b) {
    const start = new Date(a), end = new Date(b);
    if (isNaN(start) || isNaN(end)) return 0;
    return Math.round((end - start) / 86400000);
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  /* ---------- vehicle card renderer (shared by fleet + concierge) ---------- */
  function carCard(car, options) {
    const opts = options || {};
    const badges = [];
    if (car.rating >= 4.85) badges.push('<span class="badge">Top rated</span>');
    if (car.fuel_type === 'Electric' || car.fuel_type === 'Hybrid') {
      badges.push(`<span class="badge badge--teal badge--right">${escapeHtml(car.fuel_type)}</span>`);
    }

    let matchBlock = '';
    if (car.match) {
      const reasons = car.match.reasons
        .map((r) => `<li>${escapeHtml(r)}</li>`).join('');
      let signals = '';
      if (opts.showSignals && car.match.signals) {
        signals = '<div class="signals">' + Object.entries(car.match.signals).map(
          ([name, value]) => `
            <div class="signal">
              <span>${escapeHtml(name)}</span>
              <span class="track"><i style="width:${Math.round(value * 100)}%"></i></span>
              <b>${value.toFixed(2)}</b>
            </div>`
        ).join('') + '</div>';
      }
      matchBlock = `
        <div class="match">
          <div class="match__head">
            <span class="match__label">Match score</span>
            <span class="match__score">${car.match.percent}%</span>
          </div>
          <div class="match__bar"><i style="width:${car.match.percent}%"></i></div>
          <ul class="match__reasons">${reasons}</ul>
          ${signals}
        </div>`;
    }

    return `
      <article class="card reveal">
        <div class="card__media">
          ${badges.join('')}
          <img src="/static/img/car-${escapeHtml(car.slug)}.svg"
               onerror="this.onerror=null;this.src='/static/img/car-${escapeHtml(car.art_style)}.svg'"
               alt="${escapeHtml(car.make + ' ' + car.model)}" loading="lazy"
               width="460" height="200">
        </div>
        <div class="card__body">
          <span class="card__make">${escapeHtml(car.make)}</span>
          <div class="card__title">
            <h3>${escapeHtml(car.model)}</h3>
            <span class="rating">★ ${Number(car.rating).toFixed(1)}</span>
          </div>
          <p class="card__tagline">${escapeHtml(car.tagline)}</p>
          <div class="spec-row">
            <span class="spec">${car.seats} seats</span>
            <span class="spec">${escapeHtml(car.transmission)}</span>
            <span class="spec">${car.horsepower} hp</span>
            <span class="spec">${escapeHtml(car.category)}</span>
          </div>
          ${matchBlock}
          <div class="card__foot">
            <div class="price">
              <span class="cur">${currency()}</span>
              <strong>${money(car.daily_rate)}</strong>
              <span>per day</span>
            </div>
            <a class="btn btn--primary btn--sm" href="/cars/${escapeHtml(car.slug)}">View</a>
          </div>
        </div>
      </article>`;
  }

  /* ---------- scroll reveal ---------- */
  const observer = 'IntersectionObserver' in window
    ? new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-in');
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.08, rootMargin: '0px 0px -40px' })
    : null;

  function revealAll(root) {
    const nodes = (root || document).querySelectorAll('.reveal:not(.is-in)');
    if (!observer) { nodes.forEach((n) => n.classList.add('is-in')); return; }
    nodes.forEach((n) => observer.observe(n));
  }

  /* ---------- mobile nav ---------- */
  document.addEventListener('click', (e) => {
    const toggle = e.target.closest('[data-nav-toggle]');
    if (!toggle) return;
    const links = document.getElementById('nav-links');
    const open = links.classList.toggle('is-open');
    toggle.setAttribute('aria-expanded', String(open));
  });

  /* ---------- date-pair guard: return must follow pick-up ---------- */
  function linkDates(pickupEl, returnEl) {
    if (!pickupEl || !returnEl) return;
    const sync = () => {
      if (!pickupEl.value) return;
      const min = new Date(pickupEl.value);
      min.setDate(min.getDate() + 1);
      const iso = min.toISOString().slice(0, 10);
      returnEl.min = iso;
      if (returnEl.value && returnEl.value <= pickupEl.value) returnEl.value = iso;
      returnEl.dispatchEvent(new Event('change', { bubbles: true }));
    };
    pickupEl.addEventListener('change', sync);
    sync();
  }

  window.VD = { api, money, price, daysBetween, escapeHtml, carCard, revealAll, linkDates };

  document.addEventListener('DOMContentLoaded', () => {
    revealAll();
    linkDates(document.getElementById('q-pickup'), document.getElementById('q-return'));
    linkDates(document.getElementById('d-pickup'), document.getElementById('d-return'));
    linkDates(document.getElementById('c-pickup'), document.getElementById('c-return'));
    linkDates(document.getElementById('b-pickup'), document.getElementById('b-return'));
  });
})();
