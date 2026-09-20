"""Server-rendered pages.

These views call the same service layer as the API — no logic is duplicated
between the HTML and JSON surfaces.
"""

from __future__ import annotations

from datetime import date, timedelta

from flask import (
    Blueprint, abort, current_app, redirect, render_template, request, url_for
)

from app import database as db
from app.recommender import get_engine, parse_intent
from app.services import (
    BRANCHES,
    EXTRAS,
    ValidationError,
    build_quote,
    get_booking,
    get_car,
    load_fleet,
    create_booking,
)

web_bp = Blueprint("web", __name__)


@web_bp.app_context_processor
def inject_globals():
    cfg = current_app.config
    return {
        "COMPANY": cfg["COMPANY_NAME"],
        "CITY": cfg["COMPANY_CITY"],
        "CURRENCY": cfg["CURRENCY"],
        "BRANCHES": BRANCHES,
        "today": date.today().isoformat(),
        "default_return": (date.today() + timedelta(days=3)).isoformat(),
        "current_year": date.today().year,
    }


@web_bp.get("/")
def home():
    fleet = load_fleet()
    featured = sorted(fleet, key=lambda c: (-c["rating"], -c["rental_count"]))[:3]
    popular = sorted(fleet, key=lambda c: -c["rental_count"])[:6]
    rows = db.query(
        "SELECT category, COUNT(*) AS count, MIN(daily_rate) AS from_rate "
        "FROM cars WHERE is_active = 1 GROUP BY category ORDER BY from_rate"
    )
    return render_template(
        "index.html",
        featured=featured,
        popular=popular,
        categories=[dict(r) for r in rows],
        fleet_size=len(fleet),
        total_units=sum(c["total_units"] for c in fleet),
    )


@web_bp.get("/fleet")
def fleet():
    cars = load_fleet()
    rows = db.query("SELECT DISTINCT category FROM cars WHERE is_active = 1 ORDER BY category")
    return render_template(
        "fleet.html",
        cars=cars,
        categories=[r["category"] for r in rows],
        max_rate=max((c["daily_rate"] for c in cars), default=5000),
    )


@web_bp.get("/cars/<slug>")
def car_detail(slug: str):
    car = get_car(slug)
    if car is None:
        abort(404)
    engine = get_engine()
    similar_slugs = [
        s for s, _ in engine.index.search(engine._profile_text(car), top_k=4)
        if s != slug
    ][:3]
    similar = [get_car(s) for s in similar_slugs]
    quote = build_quote(car, 3, [])
    return render_template("car_detail.html", car=car, similar=similar,
                           sample_quote=quote.to_dict())


@web_bp.get("/concierge")
def concierge():
    """The AI search page."""
    examples = [
        "Something fast and flashy for my birthday, budget around 3000 a day",
        "Family of six going to the desert for a week",
        "Executive car for airport transfers and client meetings",
        "Cheapest automatic I can rent for a month",
        "Open top convertible for a weekend along the coast",
        "Electric car, low running cost, 5 seats",
    ]
    return render_template("concierge.html", examples=examples)


@web_bp.route("/book/<slug>", methods=["GET", "POST"])
def book(slug: str):
    car = get_car(slug)
    if car is None:
        abort(404)

    if request.method == "POST":
        payload = request.form.to_dict()
        payload["car_slug"] = slug
        payload["extras"] = request.form.getlist("extras")
        try:
            booking = create_booking(payload)
        except ValidationError as err:
            return render_template(
                "book.html", car=car, extras=EXTRAS, error=err.message,
                field=err.field, form=payload,
            ), 400
        return redirect(url_for("web.confirmation", reference=booking["reference"]))

    prefill = {
        "pickup_date": request.args.get("pickup_date", date.today().isoformat()),
        "return_date": request.args.get(
            "return_date", (date.today() + timedelta(days=3)).isoformat()
        ),
    }
    return render_template("book.html", car=car, extras=EXTRAS, form=prefill,
                           error=None, field=None)


@web_bp.get("/booking/<reference>")
def confirmation(reference: str):
    booking = get_booking(reference)
    if booking is None:
        abort(404)
    return render_template("confirmation.html", b=booking)


@web_bp.get("/lookup")
def lookup():
    reference = (request.args.get("reference") or "").strip()
    booking = get_booking(reference) if reference else None
    return render_template("lookup.html", booking=booking, reference=reference,
                           searched=bool(reference))
