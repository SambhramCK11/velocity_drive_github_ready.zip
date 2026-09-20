"""Render every template with Jinja2 and record the output.

worker/template.mjs is checked against Jinja itself, over contexts shaped like
the ones the real views pass. Regenerate after editing a template:

    python scripts/export-template-fixtures.py > test/template-fixtures.json
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from app import _format_money, create_app  # noqa: E402
from app.services import BRANCHES, EXTRAS, build_quote  # noqa: E402
from app.seed import FLEET  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Args(dict):
    """Stands in for request.args, which the templates call .get() on."""

    def get(self, key, default=None):
        return dict.get(self, key, default)


class Request:
    def __init__(self, endpoint, args):
        self.endpoint = endpoint
        self.args = Args(args)


app = create_app("testing")
with app.app_context():
    cars = [{**c, "features": list(c["features"])} for c in FLEET]
    by_slug = {c["slug"]: c for c in cars}
    quote = build_quote(by_slug["mercedes-s500"], 3, ["insurance"]).to_dict()
    quote_no_discount = build_quote(by_slug["nissan-sunny"], 1, []).to_dict()

categories = [
    {"category": "Economy", "count": 3, "from_rate": 99.0},
    {"category": "Luxury", "count": 4, "from_rate": 850.0},
    {"category": "Supercar", "count": 2, "from_rate": 2950.0},
]

booking = {
    "id": 1,
    "reference": "VD-A1B2C3",
    "status": "confirmed",
    "pickup_date": "2026-10-01",
    "return_date": "2026-10-04",
    "pickup_branch": "Dubai Marina",
    "days": 3,
    "daily_rate": 850.0,
    "base_total": 2550.0,
    "discount": 178.5,
    "extras_total": 225.0,
    "vat": 129.83,
    "total": 2726.33,
    "extras": [{"key": "insurance", "label": "Full Insurance Waiver"}],
    "slug": "mercedes-s500",
    "make": "Mercedes-Benz",
    "model": "S500",
    "year": 2024,
    "category": "Luxury",
    "accent_hex": "#c9a227",
    "art_style": "luxury-sedan",
    "full_name": "Asha Nair",
    "email": "asha@example.com",
    "phone": "+971500000000",
}

cancelled = {**booking, "status": "cancelled", "reference": "VD-DEAD01"}

GLOBALS = {
    "COMPANY": "Velocity Drive",
    "CITY": "Dubai",
    "CURRENCY": "AED",
    "BRANCHES": BRANCHES,
    "today": "2026-09-20",
    "default_return": "2026-09-23",
    "current_year": 2026,
}

# A scored car, as the concierge's results carry, to exercise `car.match is defined`.
scored = {**by_slug["lamborghini-huracan-evo"],
          "match": {"score": 0.8123, "percent": 81,
                    "signals": {"semantic": 0.9, "budget": 0.7},
                    "reasons": ["Strong match on fast, flashy"]}}

CASES = {
    "index.html": {
        "featured": cars[:3], "popular": cars[:6], "categories": categories,
        "fleet_size": len(cars), "total_units": sum(c["total_units"] for c in cars),
        "request": Request("web.home", {}),
    },
    "fleet.html": {
        "cars": cars, "categories": [c["category"] for c in categories],
        "max_rate": 4100.0, "request": Request("web.fleet", {"category": "Luxury"}),
    },
    "fleet.html#nofilter": {
        "_template": "fleet.html",
        "cars": cars[:2], "categories": [c["category"] for c in categories],
        "max_rate": 4100.0, "request": Request("web.fleet", {}),
    },
    "car_detail.html": {
        "car": by_slug["mercedes-s500"], "similar": cars[:3],
        "sample_quote": quote, "request": Request("web.car_detail", {}),
    },
    "car_detail.html#nodiscount": {
        "_template": "car_detail.html",
        "car": by_slug["nissan-sunny"], "similar": [],
        "sample_quote": quote_no_discount, "request": Request("web.car_detail", {}),
    },
    "concierge.html": {
        "examples": ["Something fast", "Family of six"],
        "request": Request("web.concierge", {}),
    },
    "book.html": {
        "car": by_slug["mercedes-s500"], "extras": EXTRAS,
        "form": {"pickup_date": "2026-10-01", "return_date": "2026-10-04"},
        "error": None, "field": None, "request": Request("web.book", {}),
    },
    "book.html#error": {
        "_template": "book.html",
        "car": by_slug["mercedes-s500"], "extras": EXTRAS,
        "form": {"pickup_date": "2026-10-01", "return_date": "2026-09-01",
                 "full_name": "A", "email": "bad", "phone": "1",
                 "pickup_branch": "Business Bay"},
        "error": "Return date must be after the pickup date.",
        "field": "return_date", "request": Request("web.book", {}),
    },
    "confirmation.html": {"b": booking, "request": Request("web.confirmation", {})},
    "confirmation.html#cancelled": {
        "_template": "confirmation.html", "b": cancelled,
        "request": Request("web.confirmation", {}),
    },
    "lookup.html": {
        "booking": None, "reference": "", "searched": False,
        "request": Request("web.lookup", {}),
    },
    "lookup.html#found": {
        "_template": "lookup.html", "booking": booking,
        "reference": "VD-A1B2C3", "searched": True,
        "request": Request("web.lookup", {}),
    },
    "lookup.html#missing": {
        "_template": "lookup.html", "booking": None,
        "reference": "VD-NOPE", "searched": True,
        "request": Request("web.lookup", {}),
    },
    "error.html": {"code": 404, "message": "Page not found",
                   "request": Request("web.home", {})},
    "_card.html": {"car": scored, "request": Request("web.concierge", {})},
    "_card.html#plain": {"_template": "_card.html", "car": by_slug["nissan-sunny"],
                         "request": Request("web.fleet", {})},
}

env = Environment(
    loader=FileSystemLoader(os.path.join(ROOT, "app", "templates")),
    autoescape=select_autoescape(default_for_string=True, default=True),
)
env.filters["money"] = lambda v: _format_money(v, 0)
env.filters["money2"] = lambda v: _format_money(v, 2)


def jsonable(value):
    if isinstance(value, Request):
        return {"endpoint": value.endpoint, "args": dict(value.args)}
    return value


rendered = {}
contexts = {}
for label, context in CASES.items():
    name = context.get("_template", label)
    ctx = {k: v for k, v in context.items() if k != "_template"}
    full = {**GLOBALS, **ctx, "url_for": lambda e, **kw: "/static/" + kw.get("filename", "")}
    rendered[label] = env.get_template(name).render(**full)
    contexts[label] = {
        "template": name,
        "context": {k: jsonable(v) for k, v in {**GLOBALS, **ctx}.items()},
    }

json.dump({"cases": contexts, "expected": rendered}, sys.stdout, indent=1)
