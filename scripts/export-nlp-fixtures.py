"""Generate test/nlp-fixtures.json from app/nlp.py.

The Worker's worker/nlp.mjs is a port, so its correctness is established by
comparing it against the Python it came from rather than against hand-written
expectations. Re-run after changing either side:

    python scripts/export-nlp-fixtures.py > test/nlp-fixtures.json
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.nlp import TfidfIndex, surface_forms, tokenize  # noqa: E402
from app.recommender import CarRecommender  # noqa: E402
from app.seed import FLEET  # noqa: E402

PHRASES = [
    "",
    "car",
    "Something fast and flashy for my birthday, budget around 3000 a day",
    "Family of six going to the desert for a week",
    "Executive car for airport transfers and client meetings",
    "Cheapest automatic I can rent for a month",
    "Open top convertible for a weekend along the coast",
    "Electric car, low running cost, 5 seats",
    "cheap affordable inexpensive economical",
    "SUVs crossover jeep 4x4 offroad",
    "running runner runs ran",
    "travelling travellers travelled",
    "SEVEN seater for KIDS and suitcases!!",
    "wedding bride marriage limousine",
    "a an the and or but",
    "3k budget under 2,500 aed per day",
    "ev evs battery hybrid hybrids",
    "quick rapid speedy quickest fastest powerful performance",
]

# The same corpus the recommender indexes: one document per car.
corpus = {car["slug"]: CarRecommender._profile_text(car) for car in FLEET}
index = TfidfIndex(corpus)

fixtures = {
    "tokenize": {p: tokenize(p) for p in PHRASES},
    "tokenize_no_bigrams": {p: tokenize(p, bigrams=False) for p in PHRASES},
    "surface_forms": {p: surface_forms(p) for p in PHRASES},
    "corpus": corpus,
    "idf_sample": {
        term: index._idf[term]
        for term in sorted(index._idf)[:40]
    },
    "search": {
        p: [[slug, score] for slug, score in index.search(p, top_k=5)]
        for p in PHRASES
    },
    "top_terms": {
        p: index.top_terms(index.vectorise_query(p), index.doc_ids[0], 3, surface_forms(p))
        for p in PHRASES
    },
}

json.dump(fixtures, sys.stdout, indent=1, sort_keys=False)
