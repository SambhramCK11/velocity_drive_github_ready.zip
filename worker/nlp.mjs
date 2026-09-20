/**
 * Minimal text-retrieval toolkit — a port of app/nlp.py.
 *
 * Dependency-free TF-IDF with cosine similarity, plus the tokenising and
 * normalisation around it. This is a line-for-line port rather than a
 * reimplementation: the stopword list, synonym table, suffix stripper, smoothed
 * IDF and L2 normalisation all match the Python, because the ranking the
 * concierge shows has to be the same ranking the Flask app produces.
 * test/nlp.test.mjs checks that against fixtures generated from the Python.
 *
 * Pipeline: casefold -> tokenise -> stopword filter -> light suffix stripping ->
 * unigrams + bigrams -> log-scaled TF x smoothed IDF -> L2 normalise.
 */

const TOKEN_RE = /[a-z0-9]+/g;

const words = (text) => text.trim().split(/\s+/).filter(Boolean);

export const STOPWORDS = new Set(
  words(`
a an the and or but if then than that this these those i me my we our you your
he she it they them his her its their for from with without to of in on at by
is am are was were be been being do does did doing have has had having will
would shall should can could may might must want wants wanted need needs
looking look get got give show find please would like just really very some any
about into over under again more most other such only own same so too as up
down out off no nor not there here when where which who whom how what
something anything everything nothing thing things someone anyone
`)
);

// Terms that match often but say nothing useful in a "why this car" line. They
// stay in the index — they still carry retrieval signal — and are only
// suppressed when explaining a result back to the user.
export const UNINFORMATIVE = new Set(
  words(`
day week month year per aed dhs car cars vehicle vehicle hire rent rental
drive driving book booking budget price cost rate
`)
);

// Domain synonyms folded into one canonical token, so "cheap", "budget" and
// "affordable" all hit the same dimension.
export const SYNONYMS = {
  cheap: 'budget', affordable: 'budget', inexpensive: 'budget',
  economical: 'budget', low: 'budget', value: 'budget',
  pricey: 'expensive', costly: 'expensive', premium: 'luxury',
  upmarket: 'luxury', posh: 'luxury', classy: 'luxury',
  prestigious: 'luxury', elegant: 'luxury', exclusive: 'luxury',
  quick: 'fast', rapid: 'fast', speedy: 'fast', quickest: 'fast',
  fastest: 'fast', powerful: 'fast', performance: 'fast',
  sporty: 'sports', sportscar: 'sports', supercars: 'supercar',
  exotic: 'supercar', flashy: 'supercar', showy: 'supercar',
  suvs: 'suv', crossover: 'suv', jeep: 'suv', '4x4': 'suv',
  offroad: 'suv', off: 'suv', roader: 'suv',
  ev: 'electric', evs: 'electric', battery: 'electric',
  hybrids: 'hybrid', petrolhead: 'sports',
  kids: 'family', children: 'family', child: 'family',
  families: 'family', relatives: 'family', group: 'family',
  wedding: 'wedding', marriage: 'wedding', bride: 'wedding',
  business: 'corporate', executive: 'corporate', work: 'corporate',
  client: 'corporate', meeting: 'corporate', office: 'corporate',
  airport: 'transfer', pickup: 'transfer', chauffeur: 'transfer',
  roadtrip: 'trip', holiday: 'trip', vacation: 'trip',
  tourist: 'trip', travel: 'trip', travelling: 'trip',
  desert: 'offroad', dune: 'offroad', sand: 'offroad',
  safari: 'offroad', camping: 'offroad',
  convertible: 'convertible', cabriolet: 'convertible',
  roadster: 'convertible', topless: 'convertible', roof: 'convertible',
  seater: 'seats', seat: 'seats', passengers: 'seats',
  people: 'seats', persons: 'seats', adults: 'seats',
  boot: 'luggage', trunk: 'luggage', bags: 'luggage',
  suitcases: 'luggage', suitcase: 'luggage',
  fuel: 'economy', mileage: 'economy', efficient: 'economy',
  city: 'urban', parking: 'urban', commute: 'urban',
  commuting: 'urban', traffic: 'urban',
};

// Very small suffix stripper. Deliberately conservative: it collapses obvious
// inflections without the over-stemming a full Porter implementation brings to
// a corpus this size. Order matters — longest suffix first.
const SUFFIXES = ['ingly', 'edly', 'ing', 'ers', 'er', 'ed', 'es', 's'];

function stripSuffix(token) {
  if (token.length <= 4) return token;
  for (const suffix of SUFFIXES) {
    if (token.endsWith(suffix) && token.length - suffix.length >= 4) {
      return token.slice(0, -suffix.length);
    }
  }
  return token;
}

/** All [a-z0-9]+ runs in the lowercased text, as Python's TOKEN_RE.findall. */
const rawTokens = (text) => String(text ?? '').toLowerCase().match(TOKEN_RE) ?? [];

/** Lowercase, split, drop stopwords, canonicalise, and add bigrams. */
export function tokenize(text, { bigrams = true } = {}) {
  const unigrams = [];
  for (const token of rawTokens(text)) {
    if (STOPWORDS.has(token)) continue;
    // A synonym is resolved before stemming, and can itself be a stopword.
    const canonical = SYNONYMS[token] ?? token;
    if (STOPWORDS.has(canonical)) continue;
    unigrams.push(stripSuffix(canonical));
  }

  if (!bigrams || unigrams.length < 2) return unigrams;
  const pairs = unigrams.slice(0, -1).map((a, i) => `${a}_${unigrams[i + 1]}`);
  return [...unigrams, ...pairs];
}

/** Term frequencies, in first-seen order — Python's Counter over a list. */
function counter(tokens) {
  const counts = new Map();
  for (const token of tokens) counts.set(token, (counts.get(token) ?? 0) + 1);
  return counts;
}

function l2Normalise(vector) {
  let sum = 0;
  for (const value of vector.values()) sum += value * value;
  const norm = Math.sqrt(sum);
  if (norm === 0) return vector;
  const out = new Map();
  for (const [term, value] of vector) out.set(term, value / norm);
  return out;
}

/**
 * An in-memory TF-IDF index over a fixed set of documents.
 *
 * Built once per isolate and reused across requests, so scoring a query is a
 * sparse dot product over a handful of terms.
 */
export class TfidfIndex {
  /** @param {Map<string,string>|Record<string,string>} documents */
  constructor(documents) {
    const entries = documents instanceof Map ? [...documents] : Object.entries(documents);
    this.docIds = entries.map(([id]) => id);
    this.tf = new Map();
    this.idf = new Map();
    this.vectors = new Map();

    const nDocs = Math.max(entries.length, 1);
    const docFreq = new Map();
    const termCounts = new Map();

    for (const [docId, text] of entries) {
      const counts = counter(tokenize(text));
      termCounts.set(docId, counts);
      for (const term of counts.keys()) docFreq.set(term, (docFreq.get(term) ?? 0) + 1);
    }

    // Smoothed IDF: log((1 + N) / (1 + df)) + 1, as in scikit-learn.
    for (const [term, df] of docFreq) {
      this.idf.set(term, Math.log((1 + nDocs) / (1 + df)) + 1.0);
    }

    for (const [docId, counts] of termCounts) {
      const vector = new Map();
      for (const [term, count] of counts) {
        vector.set(term, (1.0 + Math.log(count)) * (this.idf.get(term) ?? 1.0));
      }
      this.vectors.set(docId, l2Normalise(vector));
      this.tf.set(docId, counts);
    }
  }

  vectoriseQuery(text) {
    const counts = counter(tokenize(text));
    if (counts.size === 0) return new Map();
    const vector = new Map();
    for (const [term, count] of counts) {
      // Unseen terms carry no signal.
      if (!this.idf.has(term)) continue;
      vector.set(term, (1.0 + Math.log(count)) * this.idf.get(term));
    }
    return l2Normalise(vector);
  }

  /** Cosine similarity. Both vectors are L2-normalised, so this is a dot. */
  similarity(queryVector, docId) {
    let docVector = this.vectors.get(docId);
    if (!docVector || docVector.size === 0 || !queryVector || queryVector.size === 0) return 0.0;

    // Iterate the shorter vector.
    let shorter = queryVector;
    if (queryVector.size > docVector.size) {
      shorter = docVector;
      docVector = queryVector;
    }
    let total = 0;
    for (const [term, weight] of shorter) total += weight * (docVector.get(term) ?? 0.0);
    return total;
  }

  /** [docId, score] pairs, highest first. Sort is stable, as Python's is. */
  search(text, topK = null) {
    const queryVector = this.vectoriseQuery(text);
    const scored = this.docIds.map((docId) => [docId, this.similarity(queryVector, docId)]);
    scored.sort((a, b) => b[1] - a[1]);
    return topK ? scored.slice(0, topK) : scored;
  }

  /**
   * The terms contributing most to a match — used to explain results.
   *
   * `surface` maps a stem back to the word the user typed, so the explanation
   * reads "transfers" rather than the stem "transf".
   */
  topTerms(queryVector, docId, k = 3, surface = null) {
    const docVector = this.vectors.get(docId) ?? new Map();
    const contributions = [];
    for (const [term, weight] of queryVector) {
      const docWeight = docVector.get(term);
      if (term.includes('_') || !docWeight || UNINFORMATIVE.has(term)) continue;
      contributions.push([term, weight * docWeight]);
    }
    contributions.sort((a, b) => b[1] - a[1]);

    const out = [];
    const seen = new Set();
    for (const [term, score] of contributions) {
      if (score <= 0) continue;
      const word = surface?.[term] ?? term;
      if (seen.has(word) || UNINFORMATIVE.has(word)) continue;
      seen.add(word);
      out.push(word);
      if (out.length >= k) break;
    }
    return out;
  }
}

/** Map each stem produced by tokenize() back to its original word. */
export function surfaceForms(text) {
  const mapping = {};
  for (const raw of rawTokens(text)) {
    if (STOPWORDS.has(raw)) continue;
    const canonical = SYNONYMS[raw] ?? raw;
    if (STOPWORDS.has(canonical)) continue;
    const stem = stripSuffix(canonical);
    // setdefault: the first spelling seen wins.
    if (!(stem in mapping)) mapping[stem] = raw;
  }
  return mapping;
}
