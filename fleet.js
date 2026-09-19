/* Fleet browser: filters call the same /api/v1/cars endpoint as any API client. */
(function () {
  'use strict';

  const form = document.getElementById('filters');
  const grid = document.getElementById('fleet-grid');
  const empty = document.getElementById('fleet-empty');
  const count = document.getElementById('result-count');
  const priceInput = document.getElementById('f-price');
  const priceOut = document.getElementById('f-price-out');

  if (!form || !grid) return;

  // Honour ?category= from the footer / home page links.
  if (window.VD_INITIAL_CATEGORY && window.VD_INITIAL_CATEGORY !== 'all') {
    const select = document.getElementById('f-category');
    if ([...select.options].some((o) => o.value === window.VD_INITIAL_CATEGORY)) {
      select.value = window.VD_INITIAL_CATEGORY;
    }
  }

  const maxPrice = Number(priceInput.max);

  function readFilters() {
    const data = new FormData(form);
    const params = Object.fromEntries(data.entries());
    // A slider at its maximum means "no ceiling", not "<= max".
    if (Number(params.max_price) >= maxPrice) delete params.max_price;
    if (params.category === 'all') delete params.category;
    return params;
  }

  let inFlight = 0;

  async function load() {
    const ticket = ++inFlight;
    grid.setAttribute('aria-busy', 'true');
    try {
      const data = await window.VD.api.get('/api/v1/cars', readFilters());
      if (ticket !== inFlight) return;          // a newer request already won

      grid.innerHTML = data.cars.map((car) => window.VD.carCard(car)).join('');
      empty.hidden = data.count > 0;
      count.textContent = data.count === 1
        ? '1 vehicle available'
        : `${data.count} vehicles available`;
      window.VD.revealAll(grid);
    } catch (err) {
      if (ticket !== inFlight) return;
      grid.innerHTML = '';
      empty.hidden = false;
      count.textContent = err.message;
    } finally {
      grid.removeAttribute('aria-busy');
    }
  }

  // Debounce so dragging the slider or typing doesn't fire a request per event.
  let timer;
  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(load, delay);
  }

  form.addEventListener('input', (e) => {
    if (e.target === priceInput) {
      priceOut.textContent = Number(priceInput.value) >= maxPrice
        ? 'No limit'
        : window.VD.price(priceInput.value);
    }
    schedule(e.target.type === 'range' || e.target.type === 'search' ? 220 : 0);
  });
  form.addEventListener('change', () => schedule(0));
  form.addEventListener('submit', (e) => { e.preventDefault(); load(); });

  priceOut.textContent = 'No limit';
  load();
})();
