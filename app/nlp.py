"""Minimal text-retrieval toolkit.

A dependency-free TF-IDF vectoriser with cosine similarity, plus the tokenising
and normalisation utilities around it. Written out rather than pulled from
scikit-learn so the ranking maths is inspectable and the app installs with
Flask alone.

Pipeline: casefold -> tokenise -> stopword filter -> light suffix stripping ->
unigrams + bigrams -> log-scaled TF x smoothed IDF -> L2 normalise.
"""

from __future__ import annotations

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset("""
a an the and or but if then than that this these those i me my we our you your
he she it they them his her its their for from with without to of in on at by
is am are was were be been being do does did doing have has had having will
would shall should can could may might must want wants wanted need needs
looking look get got give show find please would like just really very some any
about into over under again more most other such only own same so too as up
down out off no nor not there here when where which who whom how what
something anything everything nothing thing things someone anyone
""".split())

# Terms that match often but say nothing useful in a "why this car" line.
# They stay in the index (they still carry retrieval signal); they are only
# suppressed when explaining a result back to the user.
UNINFORMATIVE = frozenset("""
day week month year per aed dhs car cars vehicle vehicle hire rent rental
drive driving book booking budget price cost rate
""".split())

# Domain synonyms folded into a single canonical token so that "cheap",
# "budget" and "affordable" all hit the same dimension.
SYNONYMS = {
    "cheap": "budget", "affordable": "budget", "inexpensive": "budget",
    "economical": "budget", "low": "budget", "value": "budget",
    "pricey": "expensive", "costly": "expensive", "premium": "luxury",
    "upmarket": "luxury", "posh": "luxury", "classy": "luxury",
    "prestigious": "luxury", "elegant": "luxury", "exclusive": "luxury",
    "quick": "fast", "rapid": "fast", "speedy": "fast", "quickest": "fast",
    "fastest": "fast", "powerful": "fast", "performance": "fast",
    "sporty": "sports", "sportscar": "sports", "supercars": "supercar",
    "exotic": "supercar", "flashy": "supercar", "showy": "supercar",
    "suvs": "suv", "crossover": "suv", "jeep": "suv", "4x4": "suv",
    "offroad": "suv", "off": "suv", "roader": "suv",
    "ev": "electric", "evs": "electric", "battery": "electric",
    "hybrids": "hybrid", "petrolhead": "sports",
    "kids": "family", "children": "family", "child": "family",
    "families": "family", "relatives": "family", "group": "family",
    "wedding": "wedding", "marriage": "wedding", "bride": "wedding",
    "business": "corporate", "executive": "corporate", "work": "corporate",
    "client": "corporate", "meeting": "corporate", "office": "corporate",
    "airport": "transfer", "pickup": "transfer", "chauffeur": "transfer",
    "roadtrip": "trip", "holiday": "trip", "vacation": "trip",
    "tourist": "trip", "travel": "trip", "travelling": "trip",
    "desert": "offroad", "dune": "offroad", "sand": "offroad",
    "safari": "offroad", "camping": "offroad",
    "convertible": "convertible", "cabriolet": "convertible",
    "roadster": "convertible", "topless": "convertible", "roof": "convertible",
    "seater": "seats", "seat": "seats", "passengers": "seats",
    "people": "seats", "persons": "seats", "adults": "seats",
    "boot": "luggage", "trunk": "luggage", "bags": "luggage",
    "suitcases": "luggage", "suitcase": "luggage",
    "fuel": "economy", "mileage": "economy", "efficient": "economy",
    "city": "urban", "parking": "urban", "commute": "urban",
    "commuting": "urban", "traffic": "urban",
}

# Very small suffix stripper. Deliberately conservative: it collapses obvious
# inflections without the over-stemming a full Porter implementation brings to
# a corpus this size.
_SUFFIXES = ("ingly", "edly", "ing", "ers", "er", "ed", "es", "s")


def _strip_suffix(token: str) -> str:
    if len(token) <= 4:
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text: str, *, bigrams: bool = True) -> list[str]:
    """Lowercase, split, drop stopwords, canonicalise, and add bigrams."""
    raw = TOKEN_RE.findall(text.lower())
    unigrams: list[str] = []
    for tok in raw:
        if tok in STOPWORDS:
            continue
        tok = SYNONYMS.get(tok, tok)
        if tok in STOPWORDS:
            continue
        unigrams.append(_strip_suffix(tok))

    if not bigrams or len(unigrams) < 2:
        return unigrams
    pairs = [f"{a}_{b}" for a, b in zip(unigrams, unigrams[1:])]
    return unigrams + pairs


class TfidfIndex:
    """An in-memory TF-IDF index over a fixed set of documents.

    The index is built once at application start and reused across requests,
    so scoring a query is a sparse dot product over a handful of terms.
    """

    def __init__(self, documents: dict[str, str]):
        self.doc_ids: list[str] = list(documents)
        self._tf: dict[str, dict[str, float]] = {}
        self._idf: dict[str, float] = {}
        self._vectors: dict[str, dict[str, float]] = {}
        self._build(documents)

    # -- construction -----------------------------------------------------
    def _build(self, documents: dict[str, str]) -> None:
        n_docs = max(len(documents), 1)
        doc_freq: Counter[str] = Counter()
        term_counts: dict[str, Counter[str]] = {}

        for doc_id, text in documents.items():
            counts = Counter(tokenize(text))
            term_counts[doc_id] = counts
            doc_freq.update(counts.keys())

        # Smoothed IDF: log((1 + N) / (1 + df)) + 1, as in scikit-learn.
        self._idf = {
            term: math.log((1 + n_docs) / (1 + df)) + 1.0
            for term, df in doc_freq.items()
        }

        for doc_id, counts in term_counts.items():
            vec = {
                term: (1.0 + math.log(count)) * self._idf.get(term, 1.0)
                for term, count in counts.items()
            }
            self._vectors[doc_id] = _l2_normalise(vec)
            self._tf[doc_id] = dict(counts)

    # -- querying ---------------------------------------------------------
    def vectorise_query(self, text: str) -> dict[str, float]:
        counts = Counter(tokenize(text))
        if not counts:
            return {}
        vec = {
            term: (1.0 + math.log(count)) * self._idf.get(term, 1.0)
            for term, count in counts.items()
            if term in self._idf          # unseen terms carry no signal
        }
        return _l2_normalise(vec)

    def similarity(self, query_vec: dict[str, float], doc_id: str) -> float:
        """Cosine similarity. Both vectors are L2-normalised, so this is a dot."""
        doc_vec = self._vectors.get(doc_id)
        if not doc_vec or not query_vec:
            return 0.0
        # Iterate the shorter vector for speed.
        if len(query_vec) > len(doc_vec):
            query_vec, doc_vec = doc_vec, query_vec
        return sum(w * doc_vec.get(term, 0.0) for term, w in query_vec.items())

    def search(self, text: str, top_k: int | None = None) -> list[tuple[str, float]]:
        qvec = self.vectorise_query(text)
        scored = [(doc_id, self.similarity(qvec, doc_id)) for doc_id in self.doc_ids]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k] if top_k else scored

    def top_terms(self, query_vec: dict[str, float], doc_id: str, k: int = 3,
                  surface: dict[str, str] | None = None) -> list[str]:
        """The terms contributing most to a match — used to explain results.

        ``surface`` maps a stem back to the word the user actually typed, so
        the explanation reads "transfers" rather than the stem "transf".
        """
        doc_vec = self._vectors.get(doc_id, {})
        contributions = [
            (term, weight * doc_vec.get(term, 0.0))
            for term, weight in query_vec.items()
            if "_" not in term and doc_vec.get(term)
            and term not in UNINFORMATIVE
        ]
        contributions.sort(key=lambda pair: pair[1], reverse=True)
        out, seen = [], set()
        for term, score in contributions:
            if score <= 0:
                continue
            word = (surface or {}).get(term, term)
            if word in seen or word in UNINFORMATIVE:
                continue
            seen.add(word)
            out.append(word)
            if len(out) >= k:
                break
        return out


def surface_forms(text: str) -> dict[str, str]:
    """Map each stem produced by ``tokenize`` back to its original word."""
    mapping: dict[str, str] = {}
    for raw in TOKEN_RE.findall(text.lower()):
        if raw in STOPWORDS:
            continue
        canonical = SYNONYMS.get(raw, raw)
        if canonical in STOPWORDS:
            continue
        mapping.setdefault(_strip_suffix(canonical), raw)
    return mapping


def _l2_normalise(vec: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vec.values()))
    if norm == 0:
        return vec
    return {term: value / norm for term, value in vec.items()}
