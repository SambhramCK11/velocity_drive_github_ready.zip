"""JSON API, base URL ``/api/v1``.

This module was missing from the repository as checked out — the front-end
JavaScript calls ``/api/v1/cars``, ``/api/v1/recommend`` and ``/api/v1/quote``,
and README.md documents twelve endpoints, but no blueprint defined them, so
every one returned 404. It is reconstructed here against the endpoint table in
README.md and the service layer in ``app.services``.

No business logic lives here. Each view validates its inputs, calls the same
functions the server-rendered pages call, and serialises the result — so a
price quoted over the API and a price rendered into a page cannot disagree.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

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

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

# How /cars sorts. "recommended" is the fleet's own default order (most
# expensive first, as load_fleet returns it), so it maps to no re-sort.
SORTERS = {
    "recommended": None,
    "price_asc": lambda c: c["daily_rate"],
    "price_desc": lambda c: -c["daily_rate"],
    "rating": lambda c: -c["rating"],
    "power": lambda c: -c["horsepower"],
    "fastest": lambda c: c["zero_to_hundred"],
    "popular": lambda c: -c["rental_count"],
}


@api_bp.errorhandler(ValidationError)
def handle_validation_error(error: ValidationError):
    """A failed business rule is a 400 naming the offending field."""
    return jsonify({"error": error.message, "field": error.field}), 400


def _float_arg(name: str) -> float | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValidationError(f"'{name}' must be a number.", name) from None


def _int_arg(name: str) -> int | None:
    value = _float_arg(name)
    return None if value is None else int(value)


def _payload() -> dict:
    """Accept a JSON body or a form post, so curl and the browser both work."""
    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError("Request body must be a JSON object.")
        return data
    return request.form.to_dict()


@api_bp.get("/health")
def health():
    fleet = load_fleet()
    return jsonify(
        {
            "status": "ok",
            "environment": current_app.config.get("ENV_NAME"),
            "company": current_app.config["COMPANY_NAME"],
            "currency": current_app.config["CURRENCY"],
            "fleet_size": len(fleet),
            "total_units": sum(c["total_units"] for c in fleet),
        }
    )


@api_bp.get("/cars")
def cars():
    """List with filter, free-text search and sort."""
    results = load_fleet()

    category = request.args.get("category")
    if category and category != "all":
        results = [c for c in results if c["category"] == category]

    max_price = _float_arg("max_price")
    if max_price is not None:
        results = [c for c in results if c["daily_rate"] <= max_price]

    min_seats = _int_arg("min_seats")
    if min_seats:
        results = [c for c in results if c["seats"] >= min_seats]

    # Exact-match filters on a car's spec columns.
    for field in ("fuel_type", "transmission", "body_style"):
        wanted = request.args.get(field)
        if wanted and wanted != "all":
            results = [c for c in results if c[field] == wanted]

    query = (request.args.get("q") or "").strip()
    if query:
        # Substring match over the fields a person would type, rather than the
        # TF-IDF index: this is the fleet filter, not the concierge, and a
        # shopper typing "bmw" expects exactly the BMWs.
        needle = query.lower()
        results = [
            c
            for c in results
            if needle in f"{c['make']} {c['model']} {c['category']} {c['body_style']}".lower()
        ]

    sort = request.args.get("sort", "recommended")
    if sort not in SORTERS:
        raise ValidationError(f"Unknown sort '{sort}'.", "sort")
    key = SORTERS[sort]
    if key is not None:
        results = sorted(results, key=key)

    return jsonify({"cars": results, "count": len(results)})


@api_bp.get("/cars/<slug>")
def car_detail(slug: str):
    car = get_car(slug)
    if car is None:
        return jsonify({"error": "not_found", "field": "slug"}), 404

    engine = get_engine()
    similar_slugs = [
        s for s, _ in engine.index.search(engine._profile_text(car), top_k=4) if s != slug
    ][:3]
    car["similar"] = [get_car(s) for s in similar_slugs]
    return jsonify({"car": car, "sample_quote": build_quote(car, 3, []).to_dict()})


@api_bp.get("/categories")
def categories():
    rows = db.query(
        "SELECT category, COUNT(*) AS count, MIN(daily_rate) AS from_rate "
        "FROM cars WHERE is_active = 1 GROUP BY category ORDER BY from_rate"
    )
    return jsonify({"categories": [dict(r) for r in rows]})


@api_bp.get("/extras")
def extras():
    return jsonify(
        {
            "extras": [{"key": key, **spec} for key, spec in EXTRAS.items()],
            "branches": BRANCHES,
            "deposit": current_app.config["SECURITY_DEPOSIT"],
            "vat_rate": current_app.config["VAT_RATE"],
        }
    )


@api_bp.get("/availability")
def availability():
    pickup = parse_date(request.args.get("pickup_date", ""), "pickup_date")
    ret = parse_date(request.args.get("return_date", ""), "return_date")
    days = rental_days(pickup, ret)
    free = available_fleet(pickup, ret)
    return jsonify(
        {
            "pickup_date": pickup.isoformat(),
            "return_date": ret.isoformat(),
            "days": days,
            "cars": free,
            "count": len(free),
        }
    )


@api_bp.post("/recommend")
def recommend():
    """Natural-language ranking."""
    data = _payload()
    query_text = str(data.get("query") or "").strip()

    overrides = {}
    for field in ("budget_max", "passengers", "days"):
        if data.get(field) not in (None, ""):
            try:
                overrides[field] = float(data[field])
            except (TypeError, ValueError):
                raise ValidationError(f"'{field}' must be a number.", field) from None
    if "passengers" in overrides:
        overrides["passengers"] = int(overrides["passengers"])
    if "days" in overrides:
        overrides["days"] = int(overrides["days"])

    if not query_text and not overrides:
        raise ValidationError(
            "Describe what you need, or set a budget or passenger count.", "query"
        )

    intent = parse_intent(query_text, overrides)

    # Dates are optional; when both are given, rank only what is actually free.
    available_slugs = None
    if data.get("pickup_date") and data.get("return_date"):
        pickup = parse_date(str(data["pickup_date"]), "pickup_date")
        ret = parse_date(str(data["return_date"]), "return_date")
        rental_days(pickup, ret)
        available_slugs = {c["slug"] for c in available_fleet(pickup, ret)}

    limit = int(data.get("limit") or 6)
    limit = max(1, min(limit, 24))

    ranked = get_engine().recommend(intent, limit=limit, available_slugs=available_slugs)
    results = [scored.to_dict() for scored in ranked]

    log_search(query_text, dict(data), results[0]["slug"] if results else "")

    return jsonify({"intent": intent.to_dict(), "results": results, "count": len(results)})


@api_bp.post("/quote")
def quote():
    """Price a rental before booking."""
    data = _payload()
    car = get_car(str(data.get("car_slug") or "").strip())
    if car is None:
        raise ValidationError("That vehicle is not in our fleet.", "car_slug")

    extra_keys = data.get("extras") or []
    if isinstance(extra_keys, str):
        extra_keys = [extra_keys]

    # Either a date window or a bare day count: the booking form sends dates,
    # while a price check before any dates are chosen sends days.
    available, remaining = True, car["total_units"]
    if data.get("pickup_date") and data.get("return_date"):
        pickup = parse_date(str(data["pickup_date"]), "pickup_date")
        ret = parse_date(str(data["return_date"]), "return_date")
        days = rental_days(pickup, ret)
        available, remaining = is_available(car, pickup, ret)
    elif data.get("days") not in (None, ""):
        try:
            days = int(data["days"])
        except (TypeError, ValueError):
            raise ValidationError("'days' must be a whole number.", "days") from None
        lo = current_app.config["MIN_RENTAL_DAYS"]
        hi = current_app.config["MAX_RENTAL_DAYS"]
        if not lo <= days <= hi:
            raise ValidationError(f"Rental length must be between {lo} and {hi} days.", "days")
    else:
        raise ValidationError(
            "Provide either pickup_date and return_date, or days.", "pickup_date"
        )

    return jsonify(
        {
            "quote": build_quote(car, days, list(extra_keys)).to_dict(),
            "available": available,
            "units_remaining": remaining,
        }
    )


@api_bp.post("/bookings")
def create():
    data = _payload()
    extra_keys = data.get("extras") or []
    if isinstance(extra_keys, str):
        extra_keys = [extra_keys]
    data["extras"] = list(extra_keys)
    booking = create_booking(data)
    return jsonify({"booking": booking}), 201


@api_bp.get("/bookings/<reference>")
def read(reference: str):
    booking = get_booking(reference)
    if booking is None:
        return jsonify({"error": "not_found", "field": "reference"}), 404
    return jsonify({"booking": booking})


@api_bp.post("/bookings/<reference>/cancel")
def cancel(reference: str):
    if not cancel_booking(reference):
        return (
            jsonify(
                {
                    "error": "That booking does not exist or is already cancelled.",
                    "field": "reference",
                }
            ),
            404,
        )
    return jsonify({"cancelled": True, "reference": reference.strip().upper()})


@api_bp.get("/stats")
def stats():
    fleet = load_fleet()
    totals = db.query(
        """
        SELECT COUNT(*)                                        AS bookings,
               COALESCE(SUM(total), 0)                         AS revenue,
               COALESCE(AVG(days), 0)                          AS avg_days,
               COALESCE(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END), 0) AS cancelled
        FROM bookings
        """,
        one=True,
    )
    categories_rows = db.query(
        """
        SELECT c.category, COUNT(b.id) AS bookings, COALESCE(SUM(b.total), 0) AS revenue
        FROM cars c
        LEFT JOIN bookings b ON b.car_id = c.id AND b.status != 'cancelled'
        GROUP BY c.category
        ORDER BY revenue DESC
        """
    )
    return jsonify(
        {
            "fleet_size": len(fleet),
            "total_units": sum(c["total_units"] for c in fleet),
            "average_daily_rate": round(
                sum(c["daily_rate"] for c in fleet) / max(len(fleet), 1), 2
            ),
            "bookings": dict(totals) if totals else {},
            "categories": [dict(r) for r in categories_rows],
            "currency": current_app.config["CURRENCY"],
        }
    )
