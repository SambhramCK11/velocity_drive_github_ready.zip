# Velocity Drive

A car rental platform for Dubai, built with Flask and SQLite, with an
**explainable recommendation engine** at its centre: you describe your trip in
plain English and the app ranks the fleet against what you actually said — then
shows you the reasoning.

```
"Family of six heading to the desert for a week, nothing too expensive"

  → passengers: 6 · categories: [SUV] · occasion: [family, adventure] · feature: [4WD]

  89%  Nissan Patrol Platinum    AED 650/day   ✓ Strong match on family, desert, suv
  87%  Toyota Land Cruiser 300   AED 720/day   ✓ Seats 7, room for your 6
  67%  Range Rover Vogue         AED 1,450/day ✓ Matches the suv class you asked for
```

---

## Quick start

```bash
pip install -r requirements.txt
python run.py
# → http://127.0.0.1:5000
```

The database is created and seeded with 18 vehicles on first run. No other
setup, no migrations, no API keys.

```bash
pip install -r requirements-dev.txt && pytest -q   # 70 tests
python tools/generate_assets.py                    # regenerate all artwork
```

---

## What's in here

| | |
|---|---|
| **Backend** | Flask 3 app factory, blueprints, SQLite via `sqlite3` |
| **Recommender** | TF-IDF + cosine similarity, written from scratch (`app/nlp.py`) |
| **Frontend** | Server-rendered Jinja2 + vanilla JS; no framework, no CDN |
| **Artwork** | Every background and vehicle is a procedurally generated SVG |
| **Tests** | 70 pytest cases covering ranking, pricing, availability and HTTP |
| **Dependencies** | Flask. That's the whole runtime. |

---

## The recommendation engine

This is the part worth reading. It runs in two stages.

### Stage 1 — Intent parsing (`app/recommender.py`)

Free text becomes a structured `Intent`:

| Signal | Extracted from | Example |
|---|---|---|
| `budget_max` | numeric patterns with qualifiers | `"under 3k"` → `3000` |
| `budget_strict` | *how* the ceiling was phrased | `"under 3000"` → hard; `"around 3000"` → soft |
| `passengers` | counts before or after a noun | `"family of six"` → `6` |
| `days` | durations, normalised to days | `"for 2 weeks"` → `14` |
| `categories` | cue words per vehicle class | `"flashy"` → Supercar |
| `occasions` | cue words per use case | `"client meetings"` → corporate |
| `features` | cue words per feature | `"desert"` → 4WD |

Two decisions here came out of testing against real phrasings:

- **A price ceiling is not a request for a cheap car.** `"supercar, budget
  around 3000"` used to put the word *budget* in the Economy class and drag
  economy cars into a supercar search. The numeric parser owns that phrasing
  now; only genuinely cheap-seeking words vote for Economy.
- **Cues match on word boundaries.** `"heading to the desert"` was matching the
  supercar cue `head`, so a Lamborghini turned up in a family SUV search. Cues
  now anchor with `\b`, which still lets `cheap` catch `cheapest`.

### Stage 2 — Weighted scoring

Every candidate gets six normalised signals, combined with weights from
`config.py`:

| Signal | Weight | What it measures |
|---|---|---|
| `semantic` | 0.34 | TF-IDF cosine between the query and the car's profile text |
| `budget` | 0.24 | How well the daily rate fits the stated budget |
| `capacity` | 0.16 | Seats vs. passengers |
| `category` | 0.14 | Explicit class preference, with partial credit for adjacent classes |
| `features` | 0.07 | Coverage of requested features |
| `quality` | 0.05 | Rating and booking-count prior |

Design notes:

- **Hard constraints filter; soft preferences score.** A car that cannot seat
  the party is removed, not penalised. A strict budget ceiling filters too —
  but if that leaves nothing, the engine falls back to the full set rather than
  showing an empty page.
- **Budget rewards good use of the budget.** A car at 85% of budget outscores
  one at 10%, because the cheap one is usually a downgrade in class. Over
  budget, the score decays exponentially — about twice as fast for a hard
  ceiling as a soft one.
- **Semantic scores are normalised across the candidate set.** Raw TF-IDF
  cosine on a short query rarely exceeds ~0.45, which would cap every result
  near 40% and make a perfect match look lukewarm. Normalising preserves the
  ordering exactly while making the reported percentage meaningful.
- **Every signal explains itself.** Each returns a reason string alongside its
  number, so the API returns `"Seats 7, room for your 6"` rather than `0.9`.
  The top contributing query terms are mapped back to the words the user
  actually typed — `"transfers"`, not the stem `"transf"`.

### Why hand-written TF-IDF

`app/nlp.py` implements tokenising, a synonym table, light suffix stripping,
smoothed IDF (`log((1+N)/(1+df)) + 1`), L2 normalisation and cosine similarity
in ~150 lines. scikit-learn would do the same in three, but for an 18-document
corpus it would add ~100 MB of dependencies to hide the one part of the system
worth being able to inspect and tune.

---

## API

Base URL `/api/v1`. All responses are JSON; validation failures return `400`
with a `field` naming the offending input.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Service status and fleet size |
| `GET` | `/cars` | List with filter, search and sort |
| `GET` | `/cars/<slug>` | One vehicle plus its three closest alternatives |
| `GET` | `/categories` | Classes with counts and starting prices |
| `GET` | `/extras` | Add-ons and branches |
| `GET` | `/availability` | Vehicles free in a date window |
| `POST` | `/recommend` | **Natural-language ranking** |
| `POST` | `/quote` | Price a rental before booking |
| `POST` | `/bookings` | Create a booking |
| `GET` | `/bookings/<ref>` | Retrieve a booking |
| `POST` | `/bookings/<ref>/cancel` | Cancel a booking |
| `GET` | `/stats` | Fleet and revenue analytics |

```bash
curl -X POST localhost:5000/api/v1/recommend \
  -H 'Content-Type: application/json' \
  -d '{"query": "executive car for airport transfers", "limit": 3}'
```

```jsonc
{
  "intent": { "categories": ["Luxury"], "occasions": ["corporate"] },
  "weights": { "semantic": 0.34, "budget": 0.24, "...": "..." },
  "results": [{
    "make": "Rolls-Royce", "model": "Ghost", "daily_rate": 4100,
    "match": {
      "percent": 78,
      "signals": { "semantic": 1.0, "budget": 0.62, "category": 1.0, "...": "..." },
      "reasons": [
        "Strong match on executive, airport, luxury",
        "Matches the luxury class you asked for",
        "Rated 5.0/5 by renters"
      ]
    }
  }]
}
```

---

## Business rules

- **Availability** uses a half-open interval test, so a hire starting the day
  another ends is not a clash. Stock is per-model: the Ghost has one unit and
  the second overlapping booking is rejected.
- **Pricing** is tiered — 3+ days save 7%, 7+ save 15%, 30+ save 25% — with 5%
  UAE VAT applied after the discount and add-ons.
- **One pricing implementation.** The live quote on the booking page calls
  `/api/v1/quote`, so the figure the customer sees is computed by the same code
  that will charge them. There is no duplicate formula in the browser.

---

## The artwork

Every image is generated by `tools/generate_assets.py` — there are no stock
photos or binary assets in the repository.

- **Hero** — a dusk skyline composed from three procedurally generated depth
  layers, a tapered spire, scattered lit windows, a sun glow and a haze band
  that stops the horizon reading as a neon bar. Seeded RNG, so it's reproducible.
- **Vehicles** — ten parametric side profiles (supercar, coupe, convertible,
  saloon, SUV, van, hatchback and more) on a shared baseline, with wheel arches
  cut out of the body by an SVG arc so tyres sit in wells rather than pasted on
  a flat sill. Each of the 18 cars is painted in its own colour, read from the
  fleet definition.
- **Backgrounds** — a blurred mesh gradient, a perspective grid, layered dunes
  and a `feTurbulence` grain overlay.

Change a colour or proportion in that file, re-run it, and the whole visual
identity regenerates.

---

## Project layout

```
velocity/
├── run.py                  local entry point
├── api/index.py            Vercel serverless entry point
├── vercel.json             routing and function config
├── config.py               environments, business rules, ranking weights
├── requirements.txt
├── app/
│   ├── __init__.py         app factory, error handlers, template filters
│   ├── database.py         schema + per-request connection handling
│   ├── seed.py             18-vehicle fleet (profile text feeds the index)
│   ├── nlp.py              TF-IDF, tokeniser, cosine similarity
│   ├── recommender.py      intent parsing + weighted scoring
│   ├── services.py         pricing, availability, bookings
│   ├── api/routes.py       REST API
│   ├── web/routes.py       server-rendered pages
│   ├── templates/          Jinja2
│   └── static/             CSS, JS, generated SVGs
├── tools/generate_assets.py
└── tests/test_app.py
```

---

## Deploying to Vercel

`api/index.py` exposes the WSGI app as a serverless function and `vercel.json`
rewrites every request to it, so Flask keeps doing its own routing — pages,
the JSON API and `/static` alike:

```json
{
  "framework": null,
  "rewrites": [{ "source": "/(.*)", "destination": "/api/index" }],
  "functions": { "api/index.py": { "includeFiles": "{app/**,config.py}" } }
}
```

Framework auto-detection is switched off on purpose. Vercel's Flask preset
probes a fixed list of root filenames — `app.py`, `index.py`, `server.py`,
`main.py` — none of which this project uses, and `includeFiles` is needed
regardless so the templates and generated SVGs are bundled with the function.

Import the repository at [vercel.com/new](https://vercel.com/new) and deploy.
There is no build command to set. `requirements.txt` is runtime-only (just
Flask), so the build does not install pytest.

Two things follow from running on a serverless platform, both handled in
`config.py`:

- **The filesystem is read-only apart from `/tmp`.** `DATABASE_PATH` defaults
  there when `VERCEL` is set, so SQLite can open the database for writing.
- **Instances are ephemeral.** The schema is created and the 18-vehicle fleet
  re-seeded on each cold start, so the catalogue, search and pricing are always
  correct — but bookings live only as long as the instance that took them. That
  is fine for a demonstration; a real deployment would point `DATABASE_PATH` at
  managed Postgres and swap the `sqlite3` calls in `app/database.py`.

Set `SECRET_KEY` in the project's environment variables. `FLASK_ENV` defaults
to `production` on Vercel, so `DEBUG` is never on in a deployment.

---

## Notes

Demonstration project — no payments are processed and no real bookings are
taken. Secrets read from the environment (`SECRET_KEY`, `DATABASE_PATH`) with
development fallbacks; a production deployment would run behind a WSGI server
with `FLASK_ENV=production`.
