"""JSON API, mounted at /api/v1.

Every endpoint delegates to the service layer, so the rules applied here are
the same ones the server-rendered pages apply — the live quote on the booking
page calls ``/quote``, and the booking form and ``/bookings`` both end up in
``services.create_booking``.

Validation failures raise ``ValidationError`` and are turned into a 400 with
the offending ``field`` by the app-level handler in ``app/__init__.py``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app import database as db
from app.recommender import get_engine, parse_intent
from app.services import (
    BRANCHES,
    EXTRAS,
    ValidationError,
    available_fleet,
    build_quote,
    cancel_booking,
    create_booking,
    get_booking,
    get_car,
    is_available,
    load_fleet,
    log_search,
    parse_date,
    rental_days,
)

api_bp = Blueprint("api", __name__)

MAX_LIMIT = 24

SORTS = {
    "price_asc":  lambda c: c["daily_rate"],
    "price_desc": lambda c: -c["daily_rate"],
    "rating":     lambda c: (-c["rating"], -c["rental_count"]),
    "power":      lambda c: -c["horsepower"],
    "fastest":    lambda c: c["zero_to_hundred"],
    "popular":    lambda c: -c["rental_count"],
    # The default ordering: well-rated, well-used cars first.
    "recommended": lambda c: (-c["rating"], -c["rental_count"]),
}


def _payload() -> dict:
    """Read a JSON body without raising on an empty or non-JSON request."""
    return request.get_json(silent=True) or {}


def _int(value, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise ValidationError(f"'{value}' is not a whole number.", field)


def _float(value, field: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        raise ValidationError(f"'{value}' is not a number.", field)


def _window(source: dict, required: bool = True):
    """Resolve a (pickup, return, days) window from dates in ``source``."""
    raw_pickup = source.get("pickup_date")
    raw_return = source.get("return_date")
    if not raw_pickup or not raw_return:
        if required:
            raise ValidationError(
                "Both 'pickup_date' and 'return_date' are required.",
                "pickup_date" if not raw_pickup else "return_date",
            )
        return None, None, None
    pickup = parse_date(raw_pickup, "pickup_date")
    ret = parse_date(raw_return, "return_date")
    return pickup, ret, rental_days(pickup, ret)


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------

@api_bp.get("/health")
def health():
    fleet = load_fleet()
    return jsonify(
        status="ok",
        service="velocity-drive",
        version="1.0",
        fleet_size=len(fleet),
        total_units=sum(c["total_units"] for c in fleet),
    )


# --------------------------------------------------------------------------
# Fleet
# --------------------------------------------------------------------------

@api_bp.get("/cars")
def list_cars():
    args = request.args
    cars = load_fleet()

    category = (args.get("category") or "").strip()
    if category and category.lower() != "all":
        cars = [c for c in cars if c["category"].lower() == category.lower()]

    fuel = (args.get("fuel_type") or "").strip()
    if fuel:
        cars = [c for c in cars if c["fuel_type"].lower() == fuel.lower()]

    transmission = (args.get("transmission") or "").strip()
    if transmission:
        cars = [c for c in cars if c["transmission"].lower() == transmission.lower()]

    min_seats = _int(args.get("min_seats"), "min_seats")
    if min_seats:
        cars = [c for c in cars if c["seats"] >= min_seats]

    max_price = _float(args.get("max_price"), "max_price")
    if max_price is not None:
        cars = [c for c in cars if c["daily_rate"] <= max_price]

    min_price = _float(args.get("min_price"), "min_price")
    if min_price is not None:
        cars = [c for c in cars if c["daily_rate"] >= min_price]

    # Free-text filter across the fields a browsing user would type into.
    term = (args.get("q") or args.get("search") or "").strip().lower()
    if term:
        def matches(car: dict) -> bool:
            haystack = " ".join([
                car["make"], car["model"], car["category"], car["body_style"],
                car["fuel_type"], car["tagline"], " ".join(car["features"]),
            ]).lower()
            return all(word in haystack for word in term.split())

        cars = [c for c in cars if matches(c)]

    sort = (args.get("sort") or "recommended").strip()
    cars.sort(key=SORTS.get(sort, SORTS["recommended"]))

    return jsonify(count=len(cars), sort=sort, cars=cars)


@api_bp.get("/cars/<slug>")
def car_detail(slug: str):
    car = get_car(slug)
    if car is None:
        return jsonify(error="not_found",
                       message="That vehicle is not in our fleet."), 404

    # Nearest neighbours in the same TF-IDF space the recommender ranks with.
    engine = get_engine()
    similar_slugs = [
        s for s, _ in engine.index.search(engine._profile_text(car), top_k=4)
        if s != slug
    ][:3]

    car = dict(car)
    car["similar"] = [get_car(s) for s in similar_slugs]
    return jsonify(car=car)


@api_bp.get("/categories")
def categories():
    rows = db.query(
        "SELECT category, COUNT(*) AS count, MIN(daily_rate) AS from_rate, "
        "       MAX(seats) AS max_seats "
        "FROM cars WHERE is_active = 1 GROUP BY category ORDER BY from_rate"
    )
    return jsonify(count=len(rows), categories=[dict(r) for r in rows])


@api_bp.get("/extras")
def extras():
    return jsonify(
        extras=[{"key": key, **spec} for key, spec in EXTRAS.items()],
        branches=BRANCHES,
    )


@api_bp.get("/availability")
def availability():
    pickup, ret, days = _window(request.args)
    cars = available_fleet(pickup, ret)
    return jsonify(
        pickup_date=pickup.isoformat(),
        return_date=ret.isoformat(),
        days=days,
        count=len(cars),
        cars=cars,
    )


# --------------------------------------------------------------------------
# Recommendation
# --------------------------------------------------------------------------

@api_bp.post("/recommend")
def recommend():
    body = _payload()
    query_text = str(body.get("query") or "").strip()

    # Structured fields the caller set explicitly beat anything parsed out of
    # the prose, and on their own they are enough to rank against.
    overrides = {}
    budget = _float(body.get("budget_max"), "budget_max")
    if budget is not None:
        overrides["budget_max"] = budget
    passengers = _int(body.get("passengers"), "passengers")
    if passengers is not None:
        overrides["passengers"] = passengers

    if not query_text and not overrides:
        raise ValidationError(
            "Describe what you need, or set a budget or passenger count.",
            "query",
        )

    limit = _int(body.get("limit"), "limit") or 6
    limit = max(1, min(limit, MAX_LIMIT))

    # An explicit date window narrows the candidates to what is actually free.
    pickup, ret, days = _window(body, required=False)
    available_slugs = None
    if pickup and ret:
        available_slugs = {c["slug"] for c in available_fleet(pickup, ret)}
        overrides.setdefault("days", days)

    intent = parse_intent(query_text, overrides)
    results = get_engine().recommend(intent, limit=limit,
                                     available_slugs=available_slugs)
    ranked = [r.to_dict() for r in results]

    log_search(query_text, body, ranked[0]["slug"] if ranked else "")

    return jsonify(
        query=query_text,
        intent=intent.to_dict(),
        weights=get_engine().weights,
        count=len(ranked),
        results=ranked,
    )


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------

@api_bp.post("/quote")
def quote():
    body = _payload()

    car = get_car(str(body.get("car_slug") or "").strip())
    if car is None:
        raise ValidationError("That vehicle is not in our fleet.", "car_slug")

    # Either an explicit day count or a date window — the booking page sends
    # dates, an API client may just ask "what does five days cost?".
    if body.get("pickup_date") or body.get("return_date"):
        pickup, ret, days = _window(body)
    else:
        pickup = ret = None
        days = _int(body.get("days"), "days")
        if not days:
            raise ValidationError("'days' is required.", "days")
        if days < 1:
            raise ValidationError("Minimum rental is 1 day.", "days")
        if days > 90:
            raise ValidationError("Maximum rental is 90 days.", "days")

    extras_in = body.get("extras") or []
    if isinstance(extras_in, str):
        extras_in = [e for e in extras_in.split(",") if e]

    built = build_quote(car, days, list(extras_in))
    payload = {
        "car": {"slug": car["slug"], "make": car["make"], "model": car["model"]},
        "quote": built.to_dict(),
    }
    if pickup and ret:
        payload["pickup_date"] = pickup.isoformat()
        payload["return_date"] = ret.isoformat()
        ok, remaining = is_available(car, pickup, ret)
        payload["available"] = ok
        payload["units_remaining"] = remaining
    return jsonify(**payload)


# --------------------------------------------------------------------------
# Bookings
# --------------------------------------------------------------------------

@api_bp.post("/bookings")
def create():
    booking = create_booking(_payload())
    return jsonify(booking=booking), 201


@api_bp.get("/bookings/<reference>")
def read_booking(reference: str):
    booking = get_booking(reference)
    if booking is None:
        return jsonify(error="not_found",
                       message="No booking with that reference."), 404
    return jsonify(booking=booking)


@api_bp.post("/bookings/<reference>/cancel")
def cancel(reference: str):
    # cancel_booking is false for both "no such reference" and "already
    # cancelled" — neither is a live booking to act on, so both are a 404.
    if not cancel_booking(reference):
        return jsonify(error="not_found",
                       message="No live booking with that reference."), 404
    return jsonify(status="cancelled", reference=reference.strip().upper())


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------

@api_bp.get("/stats")
def stats():
    fleet = load_fleet()
    rows = db.query(
        "SELECT category, COUNT(*) AS count, ROUND(AVG(daily_rate), 2) AS avg_rate "
        "FROM cars WHERE is_active = 1 GROUP BY category ORDER BY count DESC"
    )
    totals = db.query(
        "SELECT COUNT(*) AS bookings, "
        "       COALESCE(SUM(total), 0) AS revenue, "
        "       COALESCE(AVG(days), 0) AS avg_days "
        "FROM bookings WHERE status = 'confirmed'",
        one=True,
    )
    popular = sorted(fleet, key=lambda c: -c["rental_count"])[:5]

    return jsonify(
        fleet_size=len(fleet),
        total_units=sum(c["total_units"] for c in fleet),
        categories=[dict(r) for r in rows],
        bookings=int(totals["bookings"]),
        revenue=round(float(totals["revenue"]), 2),
        average_days=round(float(totals["avg_days"]), 1),
        most_rented=[
            {"slug": c["slug"], "make": c["make"], "model": c["model"],
             "rental_count": c["rental_count"]}
            for c in popular
        ],
    )
