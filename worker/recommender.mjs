/**
 * The recommendation engine — a port of app/recommender.py.
 *
 * Two stages, unchanged from the Python:
 *
 * 1. Intent parsing turns free text ("something fast and flashy for a wedding,
 *    4 people, under 1500 a day") into a structured intent: budget, passengers,
 *    category leanings, feature asks, occasion.
 * 2. Scoring blends six normalised signals into one 0–1 relevance score per
 *    car, each reporting why it fired so the API can return readable reasons.
 *
 * The cue lists, regexes, weights and arithmetic are carried over as-is;
 * test/recommender.test.mjs compares this against the Python over the real
 * fleet, because a ranking that quietly disagrees with the Flask app's would be
 * invisible until someone compared two pages side by side.
 */

import { TfidfIndex, surfaceForms, tokenize } from './nlp.mjs';

/* ------------------------------------------------------------------ */
/* Python-compatible rounding                                          */
/* ------------------------------------------------------------------ */

/**
 * Round half to even, as Python's round() does.
 *
 * Math.round rounds halves up, so Math.round(2.5) is 3 where Python gives 2.
 * The match percentages and the "% to spare" figures are produced by round(),
 * and a reader comparing the API against the Flask app would see the
 * difference, so the Python behaviour is reproduced here.
 */
export function pyRound(value, digits = 0) {
  if (!Number.isFinite(value)) return value;

  // Rounding has to happen on the number's decimal expansion, not on
  // value * 10**digits. Scaling can destroy the very information the decision
  // depends on: 2.675 is really 2.674999…, so Python gives 2.67, but
  // 2.675 * 100 evaluates to exactly 267.5 and would round to 2.68.
  // toFixed(20) exposes enough of the true expansion to decide, and reports an
  // exact tie (0.5, 2.5, 0.125) as exactly ...5000.
  const negative = value < 0;
  const [whole, fraction] = Math.abs(value).toFixed(20).split('.');
  const kept = fraction.slice(0, digits);
  const discarded = fraction.slice(digits);

  let roundUp = false;
  const first = discarded[0];
  if (first > '5') {
    roundUp = true;
  } else if (first === '5') {
    if (/[1-9]/.test(discarded.slice(1))) {
      roundUp = true; // above the halfway point
    } else {
      // An exact tie: round half to even, as Python does.
      const lastKept = digits > 0 ? kept[digits - 1] : whole[whole.length - 1];
      roundUp = Number(lastKept) % 2 === 1;
    }
  }

  // Integer arithmetic on the digits, so the increment cannot itself round.
  const scaled = BigInt(whole + kept) + (roundUp ? 1n : 0n);
  const result = digits === 0 ? Number(scaled) : Number(scaled) / 10 ** digits;
  return negative ? -result : result;
}

/**
 * Render a number the way Python's f-string does.
 *
 * Python keeps a float's decimal point — f"{5.0}" is "5.0" — while JS drops it,
 * so a 5.0 rating would read "Rated 5/5" here and "Rated 5.0/5" in the Flask
 * app for the same car.
 */
export const pyFloat = (value) =>
  Number.isInteger(value) ? `${value}.0` : String(value);

/* ------------------------------------------------------------------ */
/* Intent parsing                                                      */
/* ------------------------------------------------------------------ */

// Cues are matched as whole words or word-initial prefixes (see cueHit), so
// "cheap" catches "cheapest" without "head" catching "heading". Short
// ambiguous stems are deliberately kept out of these lists.
export const CATEGORY_CUES = {
  Supercar: ['supercar', 'lamborghini', 'ferrari', 'exotic', 'flashy',
    'showstopper', 'insane', 'jaw', 'spectacle'],
  Luxury: ['luxury', 'rolls', 'bentley', 'chauffeur', 'vip', 'corporate',
    'wedding', 'elegant', 'classy', 'prestige', 'limousine'],
  Sports: ['sports', 'sporty', 'fast', 'coupe', 'porsche', 'bmw', 'mustang',
    'muscle', 'track', 'adrenaline', 'thrill'],
  SUV: ['suv', 'offroad', 'desert', 'family', 'spacious',
    'safari', 'camping', 'rugged', 'clearance', '7 seat', 'seven seat'],
  Electric: ['electric', 'tesla', 'charge', 'charging', 'green', 'eco',
    'sustainable', 'silent', 'emission'],
  // "budget" is deliberately absent: "budget around 3000 a day" states a price
  // ceiling, not a request for an economy car. The numeric parser handles that
  // phrasing; only genuinely cheap-seeking words vote here.
  Economy: ['economy', 'cheap', 'basic', 'simple', 'student',
    'saving', 'bargain', 'commute'],
  Compact: ['compact', 'small', 'hatchback', 'mini', 'urban', 'park',
    'tiny', 'nippy'],
  Van: ['van', 'mpv', 'minibus', 'eight', 'team', 'delegation',
    'shuttle', 'everyone'],
};

export const OCCASION_CUES = {
  wedding: ['wedding', 'bride', 'groom', 'marriage', 'nikah'],
  corporate: ['corporate', 'business', 'client', 'meeting', 'conference',
    'executive', 'transfer'],
  family: ['family', 'kids', 'children', 'parents', 'school'],
  adventure: ['offroad', 'desert', 'camping', 'safari', 'dune', 'trip'],
  celebration: ['birthday', 'anniversary', 'proposal', 'celebrate',
    'graduation', 'photoshoot', 'content'],
  commute: ['commute', 'urban', 'work', 'daily', 'errand', 'month'],
};

export const FEATURE_CUES = {
  'Apple CarPlay': ['carplay', 'apple', 'android', 'phone', 'screen'],
  'Panoramic Roof': ['panoramic', 'sunroof', 'roof', 'glass', 'sky'],
  'Massage Seats': ['massage', 'comfort', 'relax'],
  '7 Seats': ['seven seat', '7 seat', 'seven-seat', '7-seat'],
  '4WD': ['offroad', 'desert', 'sand', 'dune', 'safari', '4wd', '4x4'],
  Autopilot: ['autopilot', 'self', 'driving', 'assist', 'autonomous'],
  Convertible: ['convertible', 'open', 'roof', 'cabrio', 'topless', 'wind'],
  Supercharging: ['charge', 'charging', 'supercharger', 'electric'],
};

// Numbers written as words, for "seats for six". Insertion order matters: it
// is spliced into the passenger regexes in this order, as in the Python.
const WORD_NUMBERS = {
  one: 1, two: 2, three: 3, four: 4, five: 5, six: 6,
  seven: 7, eight: 8, nine: 9, ten: 10, twelve: 12,
};

const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * True when any cue appears as a whole word or a word-initial prefix.
 *
 * Plain substring matching is what made "heading to the desert" register as a
 * supercar request ("head"), so cues must start at a word boundary.
 */
function cueHit(cues, lowered, tokens) {
  for (const cue of cues) {
    if (tokens.has(cue)) return true;
    if (new RegExp(`\\b${escapeRe(cue)}`).test(lowered)) return true;
  }
  return false;
}

const numberWords = Object.keys(WORD_NUMBERS).join('|');

// Group 1 records HOW the ceiling was phrased: "under 3000" is a hard limit,
// "around 3000" invites a near miss. The two are scored differently.
const BUDGET_RE = new RegExp(
  '(?<qualifier>under|below|less than|max(?:imum)?|up to|within|budget of|' +
    'around|about|roughly|less|<=?)\\s*(?:aed|dhs?|rs\\.?|\\$)?\\s*' +
    '(?<amount>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?<kilo>k)?',
  'i'
);
const SOFT_QUALIFIERS = ['around', 'about', 'roughly', 'budget of'];
const PLAIN_MONEY_RE = new RegExp(
  '(?:aed|dhs?|\\$)\\s*(?<amount>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?<kilo>k)?',
  'i'
);
// "6 people", "seven passengers", "2 of us"
const PASSENGER_RE = new RegExp(
  `(?<n>[0-9]{1,2}|${numberWords})\\s*` +
    '(?:people|persons?|passengers?|adults?|seats?|seater|of us|pax)',
  'i'
);
// "family of four", "group of 6", "party of eight" — the count trails the noun.
const GROUP_OF_RE = new RegExp(
  `(?:family|group|party|team|couple)\\s+of\\s+(?<n>[0-9]{1,2}|${numberWords})`,
  'i'
);
const DAYS_RE = /([0-9]{1,3})\s*(day|days|night|nights|week|weeks|month|months)/i;

/** Amount with thousands separators stripped, and a trailing "k" applied. */
function moneyFrom(match) {
  let value = Number(match.groups.amount.replace(/,/g, ''));
  if (match.groups.kilo) value *= 1000;
  return value;
}

/** Structured form of a free-text rental request. */
export class Intent {
  constructor(fields = {}) {
    this.raw_text = fields.raw_text ?? '';
    this.budget_max = fields.budget_max ?? null;
    this.budget_strict = fields.budget_strict ?? true; // false for "around"/"about"
    this.passengers = fields.passengers ?? null;
    this.days = fields.days ?? null;
    this.categories = fields.categories ?? [];
    this.features = fields.features ?? [];
    this.occasions = fields.occasions ?? [];
    this.wants_electric = fields.wants_electric ?? false;
    this.wants_automatic = fields.wants_automatic ?? true;
  }

  toJSON() {
    return {
      raw_text: this.raw_text,
      budget_max: this.budget_max,
      budget_strict: this.budget_strict,
      passengers: this.passengers,
      days: this.days,
      categories: this.categories,
      features: this.features,
      occasions: this.occasions,
      wants_electric: this.wants_electric,
    };
  }
}

/**
 * Extract structured constraints from natural language.
 *
 * `overrides` (explicit form fields from the UI) always win over anything
 * inferred from the text — a user who typed a number into the budget box means
 * it more than a phrase the parser guessed at.
 */
export function parseIntent(text, overrides = null) {
  const opts = overrides ?? {};
  const raw = String(text ?? '');
  const intent = new Intent({ raw_text: raw.trim() });
  const lowered = raw.toLowerCase();
  const tokens = new Set(tokenize(raw, { bigrams: false }));

  // Budget
  let match = BUDGET_RE.exec(lowered);
  if (match) {
    const value = moneyFrom(match);
    if (value >= 20 && value <= 200000) {
      intent.budget_max = value;
      const qualifier = (match.groups.qualifier ?? '').toLowerCase();
      intent.budget_strict = !SOFT_QUALIFIERS.includes(qualifier);
    }
  } else {
    match = PLAIN_MONEY_RE.exec(lowered);
    if (match) {
      const value = moneyFrom(match);
      if (value >= 20 && value <= 200000) {
        intent.budget_max = value;
        intent.budget_strict = true;
      }
    }
  }

  // Passengers
  match = PASSENGER_RE.exec(lowered) ?? GROUP_OF_RE.exec(lowered);
  if (match) {
    const token = match.groups.n.toLowerCase();
    let count = WORD_NUMBERS[token];
    if (count === undefined) {
      const parsed = Number.parseInt(token, 10);
      count = Number.isNaN(parsed) ? null : parsed;
    }
    if (count && count >= 1 && count <= 12) intent.passengers = count;
  }

  // Duration
  match = DAYS_RE.exec(lowered);
  if (match) {
    const n = Number.parseInt(match[1], 10);
    const unit = match[2].toLowerCase();
    const multiplier = unit.startsWith('week') ? 7 : unit.startsWith('month') ? 30 : 1;
    intent.days = Math.min(n * multiplier, 90);
  }

  // Categories, occasions, features — cue-word voting
  const vote = (cues) =>
    Object.entries(cues)
      .filter(([, list]) => cueHit(list, lowered, tokens))
      .map(([name]) => name);

  intent.categories = vote(CATEGORY_CUES);
  intent.occasions = vote(OCCASION_CUES);
  intent.features = vote(FEATURE_CUES);
  intent.wants_electric = intent.categories.includes('Electric');

  // Explicit UI fields override inference.
  if (opts.budget_max) intent.budget_max = Number(opts.budget_max);
  if (opts.passengers) intent.passengers = Number.parseInt(opts.passengers, 10);
  if (opts.days) intent.days = Number.parseInt(opts.days, 10);
  if (opts.category) intent.categories = [String(opts.category)];

  return intent;
}

/* ------------------------------------------------------------------ */
/* Scoring                                                             */
/* ------------------------------------------------------------------ */

export class ScoredCar {
  constructor(car, score, signals, reasons) {
    this.car = car;
    this.score = score;
    this.signals = signals;
    this.reasons = reasons;
  }

  toJSON() {
    const signals = {};
    for (const [key, value] of Object.entries(this.signals)) {
      signals[key] = pyRound(value, 4);
    }
    return {
      ...this.car,
      match: {
        score: pyRound(this.score, 4),
        percent: pyRound(this.score * 100),
        signals,
        reasons: this.reasons,
      },
    };
  }
}

/** Adjacent classes that still partially satisfy an ask. */
const NEIGHBOURS = {
  Supercar: ['Sports', 'Luxury'],
  Sports: ['Supercar', 'Luxury'],
  Luxury: ['Supercar', 'Sports', 'SUV'],
  SUV: ['Van', 'Luxury'],
  Van: ['SUV'],
  Economy: ['Compact', 'Electric'],
  Compact: ['Economy', 'Electric'],
  Electric: ['Economy', 'Compact'],
};

/**
 * Ranks the fleet against a parsed intent.
 *
 * Build once per isolate and call recommend() per request.
 */
export class CarRecommender {
  constructor(cars, weights) {
    this.cars = cars;
    this.weights = weights;
    this.bySlug = new Map(cars.map((car) => [car.slug, car]));

    const corpus = new Map(cars.map((car) => [car.slug, CarRecommender.profileText(car)]));
    this.index = new TfidfIndex(corpus);

    const rates = cars.length > 0 ? cars.map((car) => car.daily_rate) : [1.0];
    this.minRate = Math.min(...rates);
    this.maxRate = Math.max(...rates);
    this.maxRentals = Math.max(...(cars.length > 0 ? cars.map((c) => c.rental_count) : [1])) || 1;
  }

  /** The document indexed for a car: specs + copy + features. */
  static profileText(car) {
    return [
      car.make, car.model, car.category, car.body_style,
      car.fuel_type, car.transmission, car.color,
      car.tagline ?? '', car.description ?? '',
      (car.features ?? []).join(' '),
      `${car.seats} seats`, `${car.doors} doors`,
      `${car.luggage} luggage`,
    ].join(' ');
  }

  budgetSignal(car, intent) {
    const rate = car.daily_rate;
    if (intent.budget_max === null || intent.budget_max === undefined) {
      // No stated budget: mild preference for value within the fleet.
      const spread = Math.max(this.maxRate - this.minRate, 1.0);
      return [0.5 + 0.2 * (1 - (rate - this.minRate) / spread), null];
    }

    const budget = intent.budget_max;
    if (rate <= budget) {
      // Reward using the budget well — a car at 85% of budget scores higher
      // than one at 10%, which is usually a downgrade in class.
      const ratio = rate / budget;
      const score = 0.72 + 0.28 * Math.sin((Math.min(ratio, 1.0) * Math.PI) / 2);
      const pct = pyRound((1 - ratio) * 100);
      const reason =
        pct >= 10 ? `Fits your budget with ${pct}% to spare` : 'Uses your budget almost exactly';
      return [score, reason];
    }
    // Over budget: decay exponentially. A hard ceiling ("under 3000") decays
    // roughly twice as fast as a soft one ("around 3000"), so a near miss
    // survives the soft phrasing and is buried by the strict one.
    const overshoot = (rate - budget) / budget;
    const decay = intent.budget_strict ? 9.0 : 4.0;
    return [Math.max(0.0, Math.exp(-decay * overshoot)), null];
  }

  capacitySignal(car, intent) {
    if (intent.passengers === null || intent.passengers === undefined) return [0.6, null];
    const seats = car.seats;
    const needed = intent.passengers;
    if (seats < needed) return [0.0, null];
    const spare = seats - needed;
    if (spare === 0) return [1.0, `Seats exactly ${needed}`];
    if (spare <= 2) return [0.9, `Seats ${seats}, room for your ${needed}`];
    // Too much car for the party size is a mild penalty, not a rejection.
    return [Math.max(0.45, 0.9 - 0.12 * (spare - 2)), `Seats ${seats}`];
  }

  categorySignal(car, intent) {
    if (intent.categories.length === 0) return [0.55, null];
    if (intent.categories.includes(car.category)) {
      return [1.0, `Matches the ${car.category.toLowerCase()} class you asked for`];
    }
    const adjacent = intent.categories.some((c) => (NEIGHBOURS[c] ?? []).includes(car.category));
    return adjacent ? [0.55, null] : [0.12, null];
  }

  featureSignal(car, intent) {
    if (intent.features.length === 0) return [0.5, null];
    const owned = (car.features ?? []).map((f) => f.toLowerCase());
    const blob = `${owned.join(' ')} ${car.body_style.toLowerCase()} ${car.fuel_type.toLowerCase()}`;
    const hits = intent.features.filter((f) => blob.includes(f.toLowerCase()));
    if (hits.length === 0) return [0.15, null];
    return [hits.length / intent.features.length, `Has ${hits.slice(0, 2).join(', ')}`];
  }

  qualitySignal(car) {
    const rating = (car.rating - 3.5) / 1.5; // 3.5–5.0 -> 0–1
    const popularity = Math.log1p(car.rental_count) / Math.log1p(this.maxRentals);
    return Math.max(0.0, Math.min(1.0, 0.65 * rating + 0.35 * popularity));
  }

  /** Enrich the raw query with the structured signals we parsed. */
  static expandQuery(intent) {
    const parts = [intent.raw_text, ...intent.categories, ...intent.occasions, ...intent.features];
    if (intent.passengers) parts.push(`${intent.passengers} seats`);
    if (intent.wants_electric) parts.push('electric battery charging');
    return parts.join(' ');
  }

  recommend(intent, limit = 6, availableSlugs = null) {
    const queryText = CarRecommender.expandQuery(intent);
    const queryVector = this.index.vectoriseQuery(queryText);
    const surface = surfaceForms(intent.raw_text);
    const w = this.weights;

    // Candidate set: drop anything unavailable or physically too small.
    let candidates = this.cars.filter(
      (car) =>
        (availableSlugs === null || availableSlugs.has(car.slug)) &&
        !(intent.passengers && car.seats < intent.passengers)
    );

    // "under 3000" is a limit, not a preference, so a strict ceiling filters
    // rather than merely penalises. A 2% tolerance absorbs rounding. If that
    // leaves nothing at all we fall back to the full set rather than show an
    // empty page — the budget signal then pushes the cheapest options up.
    if (intent.budget_max && intent.budget_strict) {
      const affordable = candidates.filter((car) => car.daily_rate <= intent.budget_max * 1.02);
      if (affordable.length > 0) candidates = affordable;
    }

    // Raw TF-IDF cosine on a short query rarely exceeds ~0.45, which would cap
    // every final score well below 1 and make a genuinely perfect match read as
    // "43%". Normalising the semantic signal across the candidate set (standard
    // IR score normalisation) keeps the ordering identical while making the
    // reported percentage meaningful to a reader.
    const rawSemantic = new Map(
      candidates.map((car) => [car.slug, this.index.similarity(queryVector, car.slug)])
    );
    const best = candidates.length > 0 ? Math.max(...rawSemantic.values()) : 0.0;

    const results = [];
    for (const car of candidates) {
      const semantic = best > 0 ? rawSemantic.get(car.slug) / best : 0.0;
      const [budget, budgetReason] = this.budgetSignal(car, intent);
      const [capacity, capacityReason] = this.capacitySignal(car, intent);
      const [category, categoryReason] = this.categorySignal(car, intent);
      const [features, featureReason] = this.featureSignal(car, intent);
      const quality = this.qualitySignal(car);

      const signals = { semantic, budget, capacity, category, features, quality };
      // Summed in the weights' own key order, as the Python does.
      let score = 0;
      for (const name of Object.keys(w)) score += signals[name] * w[name];

      const reasons = [categoryReason, budgetReason, capacityReason, featureReason].filter(Boolean);
      const terms = this.index.topTerms(queryVector, car.slug, 3, surface);
      if (terms.length > 0) reasons.unshift(`Strong match on ${terms.join(', ')}`);
      if (car.rating >= 4.8) reasons.push(`Rated ${pyFloat(car.rating)}/5 by renters`);
      if (reasons.length === 0) reasons.push('A solid all-round pick from our fleet');

      results.push(new ScoredCar(car, score, signals, reasons.slice(0, 4)));
    }

    // Stable sort, matching Python's sorted(..., reverse=True).
    results.sort((a, b) => b.score - a.score);
    return results.slice(0, limit);
  }
}

/**
 * Build the engine for one request.
 *
 * The Python keeps a process-level singleton; a Worker isolate is short-lived
 * and may serve one request, so the index is built per call over the eighteen
 * cars. That costs a few milliseconds, which the caching in worker/index.mjs
 * keeps off the hot path.
 */
export const buildIndex = (cars, weights) => new CarRecommender(cars, weights);
