"""Generate test/services-fixtures.json from app/services.py.

Pricing is the part of this app a customer will check with a calculator, so the
ported quote maths is compared against the Python's for a spread of durations
and add-on combinations.

    python scripts/export-services-fixtures.py > test/services-fixtures.json
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.services import EXTRAS, build_quote, discount_for  # noqa: E402
from app.seed import FLEET  # noqa: E402

CARS = ["nissan-sunny", "mercedes-s500", "rolls-royce-ghost", "tesla-model-3-lr"]
DURATIONS = [1, 2, 3, 6, 7, 10, 29, 30, 45, 90]
EXTRA_SETS = [
    [],
    ["insurance"],
    ["insurance", "chauffeur"],
    ["airport", "extra_driver"],
    ["insurance", "chauffeur", "child_seat", "airport", "extra_driver", "unlimited_km"],
    ["free_yacht"],            # unknown keys are dropped
]

by_slug = {c["slug"]: c for c in FLEET}
app = create_app("testing")

cases = []
with app.app_context():
    for slug in CARS:
        car = dict(by_slug[slug])
        for days in DURATIONS:
            for extras in EXTRA_SETS:
                quote = build_quote(car, days, list(extras))
                cases.append(
                    {
                        "slug": slug,
                        "days": days,
                        "extras": extras,
                        "raw": {
                            "base_total": quote.base_total,
                            "discount": quote.discount,
                            "discount_pct": quote.discount_pct,
                            "extras_total": quote.extras_total,
                            "subtotal": quote.subtotal,
                            "vat": quote.vat,
                            "total": quote.total,
                        },
                        "dict": quote.to_dict(),
                    }
                )

    discounts = {str(d): discount_for(d) for d in range(0, 95)}

json.dump(
    {
        "cars": {slug: dict(by_slug[slug]) for slug in CARS},
        "extras": EXTRAS,
        "cases": cases,
        "discount_for": discounts,
    },
    sys.stdout,
    indent=1,
)
