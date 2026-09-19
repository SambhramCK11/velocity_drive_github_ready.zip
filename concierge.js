/* AI concierge: posts a natural-language request to /api/v1/recommend and
   renders the ranked results together with the parsed intent. */
(function () {
  'use strict';

  const form = document.getElementById('concierge-form');
  const results = document.getElementById('c-results');
  const status = document.getElementById('c-status');
  const submit = document.getElementById('c-submit');
  const intentBox = document.getElementById('c-intent');
  const intentTags = document.getElementById('c-intent-tags');
  const queryEl = document.getElementById('c-query');
  const explainEl = document.getElementById('c-explain');

  if (!form) return;

  /* Example chips fill the textarea and run immediately. */
  document.querySelectorAll('[data-example]').forEach((chip) => {
    chip.addEventListener('click', () => {
      queryEl.value = chip.dataset.example;
      queryEl.focus();
      form.requestSubmit();
    });
  });

  /* Turn the parsed Intent into readable chips, so the user can see what the
     parser actually understood before trusting the ranking. */
  function renderIntent(intent) {
    const tags = [];
    if (intent.budget_max) tags.push(`Budget ≤ ${window.VD.price(intent.budget_max)}/day`);
    if (intent.passengers) tags.push(`${intent.passengers} passengers`);
    if (intent.days) tags.push(`${intent.days} days`);
    (intent.categories || []).forEach((c) => tags.push(c));
    (intent.occasions || []).forEach((o) => tags.push(`Occasion: ${o}`));
    (intent.features || []).forEach((f) => tags.push(f));

    if (!tags.length) {
      intentBox.hidden = true;
      return;
    }
    intentTags.innerHTML = tags
      .map((t) => `<span class="intent-tag">${window.VD.escapeHtml(t)}</span>`)
      .join('');
    intentBox.hidden = false;
  }

  function setLoading(on) {
    submit.disabled = on;
    submit.innerHTML = on
      ? '<span class="spinner"></span> Thinking…'
      : 'Find my car';
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const data = Object.fromEntries(new FormData(form).entries());
    const payload = {
      query: (data.query || '').trim(),
      limit: 6
    };
    ['budget_max', 'passengers'].forEach((k) => {
      if (data[k]) payload[k] = Number(data[k]);
    });
    if (data.pickup_date && data.return_date) {
      payload.pickup_date = data.pickup_date;
      payload.return_date = data.return_date;
    }

    if (!payload.query && !payload.budget_max && !payload.passengers) {
      status.textContent = 'Describe what you need, or set a budget or passenger count.';
      queryEl.focus();
      return;
    }

    setLoading(true);
    status.textContent = 'Scoring the fleet…';
    results.innerHTML = '';

    try {
      const data2 = await window.VD.api.post('/api/v1/recommend', payload);
      renderIntent(data2.intent || {});

      if (!data2.count) {
        status.textContent = 'No vehicles match those constraints. Try raising the budget or freeing up the dates.';
        return;
      }

      const showSignals = explainEl && explainEl.checked;
      status.innerHTML = `Top ${data2.count} of the fleet, ranked by match score.`;
      results.innerHTML = data2.results
        .map((car) => window.VD.carCard(car, { showSignals }))
        .join('');
      window.VD.revealAll(results);
      results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
      status.textContent = err.message;
    } finally {
      setLoading(false);
    }
  });

  form.addEventListener('reset', () => {
    results.innerHTML = '';
    status.textContent = '';
    intentBox.hidden = true;
  });
})();
