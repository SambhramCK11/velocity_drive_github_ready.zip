"""Generate test/recommender-fixtures.json from app/recommender.py.

worker/recommender.mjs must rank the fleet exactly as the Flask app does, so
the port is checked against the original over the real eighteen cars.

    python scripts/export-recommender-fixtures.py > test/recommender-fixtures.json
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BaseConfig  # noqa: E402
from app.recommender import CarRecommender, parse_intent  # noqa: E402
from app.seed import FLEET  # noqa: E402

QUERIES = [
    "",
    "Something fast and flashy for my birthday, budget around 3000 a day",
    "Family of six going to the desert for a week",
    "Executive car for airport transfers and client meetings",
    "Cheapest automatic I can rent for a month",
    "Open top convertible for a weekend along the coast",
    "Electric car, low running cost, 5 seats",
    "under 500 aed per day",
    "under 3k",
    "around 3000",
    "less than 200",
    "7 seater for the family",
    "group of 8 for a team offsite",
    "party of eight",
    "two people, sporty coupe",
    "heading to the desert",          # must NOT read as Supercar via "head"
    "wedding limousine with massage seats",
    "AED 1,250 a day, panoramic roof",
    "I need a van for twelve",
    "tesla with autopilot and supercharging",
    "cheap city car for commuting and parking",
    "3 nights",
    "2 weeks",
    "5 months",
]

# parse_intent needs no app context.
intents = {q: parse_intent(q).to_dict() for q in QUERIES}

overrides_cases = [
    ["budget around 3000", {"budget_max": 900}],
    ["family of six", {"passengers": 2}],
    ["a week", {"days": 14}],
    ["something fast", {"category": "Economy"}],
]
intents_with_overrides = [
    {"query": q, "overrides": o, "intent": parse_intent(q, o).to_dict()}
    for q, o in overrides_cases
]

# The fleet as load_fleet() would hand it over: sorted by rate, features parsed.
cars = sorted(
    ({**c, "features": list(c["features"])} for c in FLEET),
    key=lambda c: -c["daily_rate"],
)
engine = CarRecommender(cars, BaseConfig.RECOMMENDER_WEIGHTS)

rankings = {}
for q in QUERIES:
    scored = engine.recommend(parse_intent(q), limit=6)
    rankings[q] = [
        {
            "slug": s.car["slug"],
            "score": s.score,
            "signals": s.signals,
            "reasons": s.reasons,
            "percent": s.to_dict()["match"]["percent"],
            "rounded_score": s.to_dict()["match"]["score"],
        }
        for s in scored
    ]

json.dump(
    {
        "weights": BaseConfig.RECOMMENDER_WEIGHTS,
        "cars": cars,
        "intents": intents,
        "intents_with_overrides": intents_with_overrides,
        "rankings": rankings,
        "profile_text": {c["slug"]: CarRecommender._profile_text(c) for c in cars},
    },
    sys.stdout,
    indent=1,
)
