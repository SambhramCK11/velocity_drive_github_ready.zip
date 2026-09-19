/* Live quote on the booking page.

   The price shown is always computed by the server via /api/v1/quote, so the
   figure the customer sees is the same one the booking endpoint will charge —
   there is no duplicate pricing formula in the browser. */
(function () {
  'use strict';

  const box = document.getElementById('quote-box');
  const form = document.getElementById('booking-form');
  if (!box || !form) return;

  const slug = box.dataset.slug;
  const pickup = document.getElementById('b-pickup');
  const ret = document.getElementById('b-return');

  const out = {
    days: document.getElementById('q-days'),
    daysLabel: document.getElementById('q-days-label'),
    base: document.getElementById('q-base'),
    discount: document.getElementById('q-discount'),
    discountRow: document.getElementById('q-discount-row'),
    discountLabel: document.getElementById('q-discount-label'),
    extras: document.getElementById('q-extras'),
    extrasRow: document.getElementById('q-extras-row'),
    vat: document.getElementById('q-vat'),
    total: document.getElementById('q-total')
  };

  function selectedExtras() {
    return [...form.querySelectorAll('input[name="extras"]:checked')].map((el) => el.value);
  }

  function setPlaceholder(text) {
    ['days', 'base', 'vat', 'total'].forEach((k) => { out[k].textContent = text; });
    out.discountRow.hidden = true;
    out.extrasRow.hidden = true;
  }

  let timer;
  async function refresh() {
    if (!pickup.value || !ret.value || ret.value <= pickup.value) {
      setPlaceholder('—');
      return;
    }

    try {
      const data = await window.VD.api.post('/api/v1/quote', {
        car_slug: slug,
        pickup_date: pickup.value,
        return_date: ret.value,
        extras: selectedExtras()
      });
      const q = data.quote;

      out.daysLabel.textContent = `Duration (${q.days} day${q.days === 1 ? '' : 's'})`;
      out.days.textContent = `${q.days} × ${window.VD.price(q.daily_rate, 2)}`;
      out.base.textContent = window.VD.price(q.base_total, 2);

      if (q.discount > 0) {
        out.discountLabel.textContent = `Multi-day saving (${q.discount_pct}%)`;
        out.discount.textContent = `−${window.VD.price(q.discount, 2)}`;
        out.discountRow.hidden = false;
      } else {
        out.discountRow.hidden = true;
      }

      if (q.extras_total > 0) {
        out.extras.textContent = window.VD.price(q.extras_total, 2);
        out.extrasRow.hidden = false;
      } else {
        out.extrasRow.hidden = true;
      }

      out.vat.textContent = window.VD.price(q.vat, 2);
      out.total.textContent = window.VD.price(q.total, 2);
    } catch (err) {
      setPlaceholder('—');
      out.total.textContent = err.message;
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(refresh, 120);
  }

  form.addEventListener('change', schedule);
  pickup.addEventListener('change', schedule);
  ret.addEventListener('change', schedule);
  refresh();
})();
