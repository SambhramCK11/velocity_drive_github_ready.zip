"""The recommendation engine.

Two stages:

1. **Intent parsing** turns a free-text request ("something fast and flashy for
   a wedding, 4 people, under 1500 a day") into a structured ``Intent``:
   budget, passengers, category leanings, feature asks, occasion.

2. **Scoring** blends six normalised signals into one 0-1 relevance score per
   car. Every signal reports back *why* it fired, so the API returns
   human-readable match reasons rather than an opaque number.

The weights live in ``config.RECOMMENDER_WEIGHTS`` so ranking behaviour is
tuned in one place and covered by tests.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.nlp import TfidfIndex, surface_forms, tokenize

# --------------------------------------------------------------------------
# Intent parsing
# --------------------------------------------------------------------------

CATEGORY_CUES: dict[str, tuple[str, ...]] = {
    # Cues are matched as whole words or word-initial prefixes (see _cue_hit),
    # so "cheap" catches "cheapest" without "head" catching "heading". Short
    # ambiguous stems are deliberately kept out of these lists.
    "Supercar": ("supercar", "lamborghini", "ferrari", "exotic", "flashy",
                 "showstopper", "insane", "jaw", "spectacle"),
    "Luxury": ("luxury", "rolls", "bentley", "chauffeur", "vip", "corporate",
               "wedding", "elegant", "classy", "prestige", "limousine"),
    "Sports": ("sports", "sporty", "fast", "coupe", "porsche", "bmw", "mustang",
               "muscle", "track", "adrenaline", "thrill"),
    "SUV": ("suv", "offroad", "desert", "family", "spacious",
            "safari", "camping", "rugged", "clearance", "7 seat", "seven seat"),
    "Electric": ("electric", "tesla", "charge", "charging", "green", "eco",
                 "sustainable", "silent", "emission"),
    # "budget" is deliberately absent: "budget around 3000 a day" states a
    # price ceiling, not a request for an economy car. The numeric parser
    # handles that phrasing; only genuinely cheap-seeking words vote here.
    "Economy": ("economy", "cheap", "basic", "simple", "student",
                "saving", "bargain", "commute"),
    "Compact": ("compact", "small", "hatchback", "mini", "urban", "park",
                "tiny", "nippy"),
    "Van": ("van", "mpv", "minibus", "eight", "team", "delegation",
            "shuttle", "everyone"),
}


def _cue_hit(cues: tuple[str, ...], lowered: str, tokens: set[str]) -> bool:
    """True when any cue appears as a whole word or a word-initial prefix.

    Plain substring matching is what made "heading to the desert" register as
    a supercar request ("head"), so cues must start at a word boundary.
    """
    for cue in cues:
        if cue in tokens:
            return True
        if re.search(r"\b" + re.escape(cue), lowered):
            return True
    return False

OCCASION_CUES: dict[str, tuple[str, ...]] = {
    "wedding": ("wedding", "bride", "groom", "marriage", "nikah"),
    "corporate": ("corporate", "business", "client", "meeting", "conference",
                  "executive", "transfer"),
    "family": ("family", "kids", "children", "parents", "school"),
    "adventure": ("offroad", "desert", "camping", "safari", "dune", "trip"),
    "celebration": ("birthday", "anniversary", "proposal", "celebrate",
                    "graduation", "photoshoot", "content"),
    "commute": ("commute", "urban", "work", "daily", "errand", "month"),
}

FEATURE_CUES: dict[str, tuple[str, ...]] = {
    "Apple CarPlay": ("carplay", "apple", "android", "phone", "screen"),
    "Panoramic Roof": ("panoramic", "sunroof", "roof", "glass", "sky"),
    "Massage Seats": ("massage", "comfort", "relax"),
    "7 Seats": ("seven seat", "7 seat", "seven-seat", "7-seat"),
    "4WD": ("offroad", "desert", "sand", "dune", "safari", "4wd", "4x4"),
    "Autopilot": ("autopilot", "self", "driving", "assist", "autonomous"),
    "Convertible": ("convertible", "open", "roof", "cabrio", "topless", "wind"),
    "Supercharging": ("charge", "charging", "supercharger", "electric"),
}

# Numbers written as words, for "seats for six"
WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
}

# Group 1 records HOW the ceiling was phrased: "under 3000" is a hard limit,
# "around 3000" invites a near miss. The two are scored differently.
_BUDGET_RE = re.compile(
    r"(?P<qualifier>under|below|less than|max(?:imum)?|up to|within|budget of|"
    r"around|about|roughly|less|<=?)\s*(?:aed|dhs?|rs\.?|\$)?\s*"
    r"(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<kilo>k)?",
    re.I,
)
_SOFT_QUALIFIERS = ("around", "about", "roughly", "budget of")
_PLAIN_MONEY_RE = re.compile(
    r"(?:aed|dhs?|\$)\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<kilo>k)?", re.I
)
# "6 people", "seven passengers", "2 of us"
_PASSENGER_RE = re.compile(
    r"(?P<n>[0-9]{1,2}|" + "|".join(WORD_NUMBERS) + r")\s*"
    r"(?:people|persons?|passengers?|adults?|seats?|seater|of us|pax)",
    re.I,
)
# "family of four", "group of 6", "party of eight" — the count trails the noun.
_GROUP_OF_RE = re.compile(
    r"(?:family|group|party|team|couple)\s+of\s+"
    r"(?P<n>[0-9]{1,2}|" + "|".join(WORD_NUMBERS) + r")",
    re.I,
)
_DAYS_RE = re.compile(r"([0-9]{1,3})\s*(day|days|night|nights|week|weeks|month|months)", re.I)


@dataclass
class Intent:
    """Structured form of a free-text rental request."""

    raw_text: str = ""
    budget_max: float | None = None
    budget_strict: bool = True    # False when phrased as "around" / "about"
    passengers: int | None = None
    days: int | None = None
    categories: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    occasions: list[str] = field(default_factory=list)
    wants_electric: bool = False
    wants_automatic: bool = True

    def to_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "budget_max": self.budget_max,
            "budget_strict": self.budget_strict,
            "passengers": self.passengers,
            "days": self.days,
            "categories": self.categories,
            "features": self.features,
            "occasions": self.occasions,
            "wants_electric": self.wants_electric,
        }


def _money(match: re.Match) -> float:
    value = float(match.group("amount").replace(",", ""))
    if match.group("kilo"):      # trailing "k", as in "under 3k"
        value *= 1000
    return value


def parse_intent(text: str, overrides: dict | None = None) -> Intent:
    """Extract structured constraints from natural language.

    ``overrides`` (explicit form fields from the UI) always win over anything
    inferred from the text — a user who typed a number into the budget box
    means it more than a phrase the parser guessed at.
    """
    overrides = overrides or {}
    intent = Intent(raw_text=text.strip())
    lowered = text.lower()
    tokens = set(tokenize(text, bigrams=False))

    # Budget
    match = _BUDGET_RE.search(lowered)
    if match:
        value = _money(match)
        if 20 <= value <= 200_000:
            intent.budget_max = value
            qualifier = (match.group("qualifier") or "").lower()
            intent.budget_strict = qualifier not in _SOFT_QUALIFIERS
    else:
        match = _PLAIN_MONEY_RE.search(lowered)
        if match:
            value = _money(match)
            if 20 <= value <= 200_000:
                intent.budget_max = value
                intent.budget_strict = True

    # Passengers
    match = _PASSENGER_RE.search(lowered) or _GROUP_OF_RE.search(lowered)
    if match:
        token = match.group("n").lower()
        count = WORD_NUMBERS.get(token, None)
        if count is None:
            try:
                count = int(token)
            except ValueError:
                count = None
        if count and 1 <= count <= 12:
            intent.passengers = count

    # Duration
    match = _DAYS_RE.search(lowered)
    if match:
        n = int(match.group(1))
        unit = match.group(2).lower()
        multiplier = 7 if unit.startswith("week") else 30 if unit.startswith("month") else 1
        intent.days = min(n * multiplier, 90)

    # Categories, occasions, features — cue-word voting
    intent.categories = [
        name for name, cues in CATEGORY_CUES.items()
        if _cue_hit(cues, lowered, tokens)
    ]
    intent.occasions = [
        name for name, cues in OCCASION_CUES.items()
        if _cue_hit(cues, lowered, tokens)
    ]
    intent.features = [
        name for name, cues in FEATURE_CUES.items()
        if _cue_hit(cues, lowered, tokens)
    ]
    intent.wants_electric = "Electric" in intent.categories

    # Explicit UI fields override inference
    if overrides.get("budget_max"):
        intent.budget_max = float(overrides["budget_max"])
    if overrides.get("passengers"):
        intent.passengers = int(overrides["passengers"])
    if overrides.get("days"):
        intent.days = int(overrides["days"])
    if overrides.get("category"):
        intent.categories = [str(overrides["category"])]

    return intent


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

@dataclass
class ScoredCar:
    car: dict
    score: float
    signals: dict[str, float]
    reasons: list[str]

    def to_dict(self) -> dict:
        payload = dict(self.car)
        payload["match"] = {
            "score": round(self.score, 4),
            "percent": round(self.score * 100),
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "reasons": self.reasons,
        }
        return payload


class CarRecommender:
    """Ranks the fleet against a parsed intent.

    Build once per process (``build_index``) and call ``recommend`` per request.
    """

    def __init__(self, cars: list[dict], weights: dict[str, float]):
        self.cars = cars
        self.weights = weights
        self.by_slug = {car["slug"]: car for car in cars}
        self.index = TfidfIndex({car["slug"]: self._profile_text(car) for car in cars})
        rates = [car["daily_rate"] for car in cars] or [1.0]
        self._min_rate, self._max_rate = min(rates), max(rates)
        self._max_rentals = max((car["rental_count"] for car in cars), default=1) or 1

    # -- corpus ------------------------------------------------------------
    @staticmethod
    def _profile_text(car: dict) -> str:
        """The document indexed for a car: specs + copy + features."""
        return " ".join(
            [
                car["make"], car["model"], car["category"], car["body_style"],
                car["fuel_type"], car["transmission"], car["color"],
                car.get("tagline", ""), car.get("description", ""),
                " ".join(car.get("features", [])),
                f"{car['seats']} seats", f"{car['doors']} doors",
                f"{car['luggage']} luggage",
            ]
        )

    # -- individual signals -------------------------------------------------
    def _budget_signal(self, car: dict, intent: Intent) -> tuple[float, str | None]:
        rate = car["daily_rate"]
        if intent.budget_max is None:
            # No stated budget: mild preference for value within the fleet.
            spread = max(self._max_rate - self._min_rate, 1.0)
            return 0.5 + 0.2 * (1 - (rate - self._min_rate) / spread), None

        budget = intent.budget_max
        if rate <= budget:
            # Reward using the budget well — a car at 85% of budget scores
            # higher than one at 10%, which is usually a downgrade in class.
            ratio = rate / budget
            score = 0.72 + 0.28 * math.sin(min(ratio, 1.0) * math.pi / 2)
            pct = round((1 - ratio) * 100)
            reason = (
                f"Fits your budget with {pct}% to spare"
                if pct >= 10 else "Uses your budget almost exactly"
            )
            return score, reason
        # Over budget: decay exponentially. A hard ceiling ("under 3000")
        # decays roughly twice as fast as a soft one ("around 3000"), so a
        # near miss survives the soft phrasing and is buried by the strict one.
        overshoot = (rate - budget) / budget
        decay = 9.0 if intent.budget_strict else 4.0
        return max(0.0, math.exp(-decay * overshoot)), None

    def _capacity_signal(self, car: dict, intent: Intent) -> tuple[float, str | None]:
        if intent.passengers is None:
            return 0.6, None
        seats, needed = car["seats"], intent.passengers
        if seats < needed:
            return 0.0, None
        spare = seats - needed
        if spare == 0:
            return 1.0, f"Seats exactly {needed}"
        if spare <= 2:
            return 0.9, f"Seats {seats}, room for your {needed}"
        # Too much car for the party size is a mild penalty, not a rejection.
        return max(0.45, 0.9 - 0.12 * (spare - 2)), f"Seats {seats}"

    def _category_signal(self, car: dict, intent: Intent) -> tuple[float, str | None]:
        if not intent.categories:
            return 0.55, None
        if car["category"] in intent.categories:
            return 1.0, f"Matches the {car['category'].lower()} class you asked for"
        # Adjacent classes still partially satisfy the ask.
        neighbours = {
            "Supercar": {"Sports", "Luxury"}, "Sports": {"Supercar", "Luxury"},
            "Luxury": {"Supercar", "Sports", "SUV"}, "SUV": {"Van", "Luxury"},
            "Van": {"SUV"}, "Economy": {"Compact", "Electric"},
            "Compact": {"Economy", "Electric"}, "Electric": {"Economy", "Compact"},
        }
        if any(car["category"] in neighbours.get(c, set()) for c in intent.categories):
            return 0.55, None
        return 0.12, None

    def _feature_signal(self, car: dict, intent: Intent) -> tuple[float, str | None]:
        if not intent.features:
            return 0.5, None
        owned = {f.lower() for f in car.get("features", [])}
        blob = " ".join(owned) + " " + car["body_style"].lower() + " " + car["fuel_type"].lower()
        hits = [f for f in intent.features if f.lower() in blob]
        if not hits:
            return 0.15, None
        coverage = len(hits) / len(intent.features)
        return coverage, f"Has {', '.join(hits[:2])}"

    def _quality_signal(self, car: dict) -> float:
        rating = (car["rating"] - 3.5) / 1.5          # 3.5-5.0 -> 0-1
        popularity = math.log1p(car["rental_count"]) / math.log1p(self._max_rentals)
        return max(0.0, min(1.0, 0.65 * rating + 0.35 * popularity))

    # -- main entry point ---------------------------------------------------
    def recommend(
        self,
        intent: Intent,
        limit: int = 6,
        available_slugs: set[str] | None = None,
    ) -> list[ScoredCar]:
        query_text = self._expand_query(intent)
        query_vec = self.index.vectorise_query(query_text)
        surface = surface_forms(intent.raw_text)
        w = self.weights

        # Candidate set: drop anything unavailable or physically too small.
        candidates = [
            car for car in self.cars
            if (available_slugs is None or car["slug"] in available_slugs)
            and not (intent.passengers and car["seats"] < intent.passengers)
        ]

        # "under 3000" is a limit, not a preference, so a strict ceiling filters
        # rather than merely penalises. A 2% tolerance absorbs rounding. If that
        # leaves nothing at all we fall back to the full set rather than show an
        # empty page — the budget signal then pushes the cheapest options up.
        if intent.budget_max and intent.budget_strict:
            affordable = [
                car for car in candidates
                if car["daily_rate"] <= intent.budget_max * 1.02
            ]
            if affordable:
                candidates = affordable

        # Raw TF-IDF cosine on a short query rarely exceeds ~0.45, which would
        # cap every final score well below 1 and make a genuinely perfect match
        # read as "43%". Normalising the semantic signal across the candidate
        # set (standard IR score normalisation) keeps the *ordering* identical
        # while making the reported percentage meaningful to a reader.
        raw_semantic = {
            car["slug"]: self.index.similarity(query_vec, car["slug"])
            for car in candidates
        }
        best = max(raw_semantic.values(), default=0.0)

        results: list[ScoredCar] = []
        for car in candidates:
            semantic = (raw_semantic[car["slug"]] / best) if best > 0 else 0.0
            budget, budget_reason = self._budget_signal(car, intent)
            capacity, capacity_reason = self._capacity_signal(car, intent)
            category, category_reason = self._category_signal(car, intent)
            features, feature_reason = self._feature_signal(car, intent)
            quality = self._quality_signal(car)

            signals = {
                "semantic": semantic, "budget": budget, "capacity": capacity,
                "category": category, "features": features, "quality": quality,
            }
            score = sum(signals[name] * w[name] for name in w)

            reasons = [r for r in (category_reason, budget_reason,
                                   capacity_reason, feature_reason) if r]
            terms = self.index.top_terms(query_vec, car["slug"], k=3,
                                         surface=surface)
            if terms:
                reasons.insert(0, "Strong match on " + ", ".join(terms))
            if car["rating"] >= 4.8:
                reasons.append(f"Rated {car['rating']}/5 by renters")
            if not reasons:
                reasons.append("A solid all-round pick from our fleet")

            results.append(ScoredCar(car, score, signals, reasons[:4]))

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    @staticmethod
    def _expand_query(intent: Intent) -> str:
        """Enrich the raw query with the structured signals we parsed."""
        parts = [intent.raw_text]
        parts.extend(intent.categories)
        parts.extend(intent.occasions)
        parts.extend(intent.features)
        if intent.passengers:
            parts.append(f"{intent.passengers} seats")
        if intent.wants_electric:
            parts.append("electric battery charging")
        return " ".join(parts)


# --------------------------------------------------------------------------
# Process-level singleton
# --------------------------------------------------------------------------

_ENGINE: CarRecommender | None = None


def build_index(cars: list[dict], weights: dict[str, float]) -> CarRecommender:
    global _ENGINE
    _ENGINE = CarRecommender(cars, weights)
    return _ENGINE


def get_engine() -> CarRecommender:
    if _ENGINE is None:
        raise RuntimeError("Recommender not initialised; call build_index() first.")
    return _ENGINE
