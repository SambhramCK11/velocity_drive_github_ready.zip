"""Generate db/seed.sql from app/seed.py's FLEET.

The fleet is defined once, in Python. Rather than transcribe eighteen cars into
SQL by hand — and have the two copies drift the first time a rate changes — this
emits the INSERT statements from the same list ``seed_fleet()`` uses.

    python scripts/export-fleet.py > db/seed.sql

Re-run it after editing FLEET.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.seed import FLEET  # noqa: E402

COLUMNS = [
    "slug", "make", "model", "year", "category", "body_style", "transmission",
    "fuel_type", "seats", "doors", "luggage", "horsepower", "zero_to_hundred",
    "daily_rate", "deposit", "rating", "rental_count", "total_units", "color",
    "accent_hex", "art_style", "features", "tagline", "description",
]


def literal(value: object) -> str:
    """Render a Python value as a Postgres literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, dict)):
        value = json.dumps(value)
    return "'" + str(value).replace("'", "''") + "'"


def main() -> None:
    print("-- Velocity Drive fleet — GENERATED FILE, do not edit by hand.")
    print("--")
    print("-- Regenerate with:  python scripts/export-fleet.py > db/seed.sql")
    print("--")
    print("-- Emitted from app/seed.py's FLEET so the Worker and the Flask app")
    print("-- describe the same eighteen cars. ON CONFLICT DO NOTHING mirrors the")
    print("-- INSERT OR IGNORE in seed_fleet(), making re-runs a no-op.")
    print()
    print(f"INSERT INTO cars ({', '.join(COLUMNS)}) VALUES")

    rows = []
    for car in FLEET:
        values = ", ".join(literal(car[column]) for column in COLUMNS)
        rows.append(f"    ({values})")
    print(",\n".join(rows))
    print("ON CONFLICT (slug) DO NOTHING;")


if __name__ == "__main__":
    main()
