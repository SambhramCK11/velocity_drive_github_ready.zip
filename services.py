"""Domain services: pricing, availability and booking creation.

Kept separate from the HTTP layer so the rules can be unit-tested without a
request context, and so the API and the server-rendered pages share exactly
one implementation.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import date, datetime

from flask import current_app

from app import database as db

DATE_FMT = "%Y-%m-%d"

EXTRAS: dict[str, dict] = {
    "insurance":      {"label": "Full Insurance Waiver", "per_day": 75.0, "flat": 0.0},
    "chauffeur":      {"label": "Professional Chauffeur", "per_day": 450.0, "flat": 0.0},
    "child_seat":     {"label": "Child Seat", "per_day": 25.0, "flat": 0.0},
    "airport":        {"label": "Airport Delivery & Collection", "per_day": 0.0, "flat": 150.0},
    "extra_driver":   {"label": "Additional Driver", "per_day": 0.0, "flat": 120.0},
    "unlimited_km":   {"label": "Unlimited Kilometres", "per_day": 60.0, "flat": 0.0},
}

BRANCHES = ["Dubai Marina", "Downtown Dubai", "DXB Terminal 3",
            "Business Bay", "Jumeirah Beach Road"]


class ValidationError(ValueError):
    """Raised when user input fails a business rule."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------

def row_to_car(row) -> dict:
    car = dict(row)
    car["features"] = json.loads(car.get("features") or "[]")
    car["daily_rate"] = float(car["daily_rate"])
    car["availability"] = max(0, int(car.get("total_units", 1)))
    return car


def load_fleet(active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM cars"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY daily_rate DESC"
    return [row_to_car(r) for r in db.query(sql)]


def get_car(slug: str) -> dict | None:
    row = db.query("SELECT * FROM cars WHERE slug = ?", (slug,), one=True)
    return row_to_car(row) if row else None


# --------------------------------------------------------------------------
# Dates and availability
# --------------------------------------------------------------------------

def parse_date(value: str, field: str) -> date:
    try:
        return datetime.strptime(str(value).strip(), DATE_FMT).date()
    except (ValueError, TypeError):
        raise ValidationError(f"'{value}' is not a valid date (expected YYYY-MM-DD).", field)


def rental_days(pickup: date, ret: date) -> int:
    cfg = current_app.config
    if ret <= pickup:
        raise ValidationError("Return date must be after the pickup date.", "return_date")
    days = (ret - pickup).days
    if days < cfg["MIN_RENTAL_DAYS"]:
        raise ValidationError(f"Minimum rental is {cfg['MIN_RENTAL_DAYS']} day(s).", "return_date")
    if days > cfg["MAX_RENTAL_DAYS"]:
        raise ValidationError(f"Maximum rental is {cfg['MAX_RENTAL_DAYS']} days.", "return_date")
    return days


def units_booked(car_id: int, pickup: date, ret: date) -> int:
    """Count confirmed bookings on a car whose window overlaps [pickup, ret).

    Two ranges overlap when each starts before the other ends — the standard
    half-open interval test, so a return on the same day a new hire starts is
    not treated as a clash.
    """
    row = db.query(
        """
        SELECT COUNT(*) AS n FROM bookings
        WHERE car_id = ? AND status = 'confirmed'
          AND pickup_date < ? AND return_date > ?
        """,
        (car_id, ret.strftime(DATE_FMT), pickup.strftime(DATE_FMT)),
        one=True,
    )
    return int(row["n"]) if row else 0


def is_available(car: dict, pickup: date, ret: date) -> tuple[bool, int]:
    taken = units_booked(car["id"], pickup, ret)
    remaining = max(0, int(car["total_units"]) - taken)
    return remaining > 0, remaining


def available_fleet(pickup: date, ret: date, cars: list[dict] | None = None) -> list[dict]:
    fleet = cars if cars is not None else load_fleet()
    out = []
    for car in fleet:
        ok, remaining = is_available(car, pickup, ret)
        if ok:
            car = dict(car)
            car["availability"] = remaining
            out.append(car)
    return out


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------

@dataclass
class Quote:
    days: int
    daily_rate: float
    base_total: float
    discount: float
    discount_pct: float
    extras_total: float
    extras: list[dict]
    subtotal: float
    vat: float
    total: float
    deposit: float
    currency: str

    def to_dict(self) -> dict:
        return {
            "days": self.days,
            "daily_rate": round(self.daily_rate, 2),
            "base_total": round(self.base_total, 2),
            "discount": round(self.discount, 2),
            "discount_pct": round(self.discount_pct * 100),
            "extras": self.extras,
            "extras_total": round(self.extras_total, 2),
            "subtotal": round(self.subtotal, 2),
            "vat": round(self.vat, 2),
            "total": round(self.total, 2),
            "deposit": round(self.deposit, 2),
            "currency": self.currency,
        }


def discount_for(days: int) -> float:
    for threshold, pct in current_app.config["DISCOUNT_TIERS"]:
        if days >= threshold:
            return pct
    return 0.0


def build_quote(car: dict, days: int, extra_keys: list[str] | None = None) -> Quote:
    cfg = current_app.config
    extra_keys = [k for k in (extra_keys or []) if k in EXTRAS]

    base_total = car["daily_rate"] * days
    pct = discount_for(days)
    discount = base_total * pct

    chosen = []
    extras_total = 0.0
    for key in extra_keys:
        spec = EXTRAS[key]
        cost = spec["per_day"] * days + spec["flat"]
        extras_total += cost
        chosen.append({"key": key, "label": spec["label"], "cost": round(cost, 2)})

    subtotal = base_total - discount + extras_total
    vat = subtotal * cfg["VAT_RATE"]
    return Quote(
        days=days,
        daily_rate=car["daily_rate"],
        base_total=base_total,
        discount=discount,
        discount_pct=pct,
        extras_total=extras_total,
        extras=chosen,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        deposit=float(car.get("deposit") or cfg["SECURITY_DEPOSIT"]),
        currency=cfg["CURRENCY"],
    )


# --------------------------------------------------------------------------
# Bookings
# --------------------------------------------------------------------------

def _reference() -> str:
    return "VD-" + secrets.token_hex(3).upper()


def create_booking(payload: dict) -> dict:
    """Validate, price and persist a booking. Raises ValidationError."""
    required = ("car_slug", "pickup_date", "return_date", "full_name", "email", "phone")
    for field in required:
        if not str(payload.get(field, "")).strip():
            raise ValidationError(f"'{field.replace('_', ' ')}' is required.", field)

    email = str(payload["email"]).strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValidationError("Please enter a valid email address.", "email")

    car = get_car(str(payload["car_slug"]).strip())
    if car is None:
        raise ValidationError("That vehicle is not in our fleet.", "car_slug")

    pickup = parse_date(payload["pickup_date"], "pickup_date")
    ret = parse_date(payload["return_date"], "return_date")
    days = rental_days(pickup, ret)

    if pickup < date.today():
        raise ValidationError("Pickup date cannot be in the past.", "pickup_date")

    ok, remaining = is_available(car, pickup, ret)
    if not ok:
        raise ValidationError(
            f"All {car['total_units']} unit(s) of the {car['make']} {car['model']} "
            "are booked for those dates.",
            "pickup_date",
        )

    branch = str(payload.get("pickup_branch") or BRANCHES[0])
    if branch not in BRANCHES:
        raise ValidationError("Unknown pickup branch.", "pickup_branch")

    extras = payload.get("extras") or []
    if isinstance(extras, str):
        extras = [e for e in extras.split(",") if e]
    quote = build_quote(car, days, extras)

    customer_id = db.execute(
        "INSERT INTO customers (full_name, email, phone, licence_no) VALUES (?,?,?,?)",
        (str(payload["full_name"]).strip(), email, str(payload["phone"]).strip(),
         str(payload.get("licence_no", "")).strip()),
    )

    reference = _reference()
    booking_id = db.execute(
        """
        INSERT INTO bookings (
            reference, car_id, customer_id, pickup_date, return_date,
            pickup_branch, days, base_total, discount, extras_total, vat,
            total, extras, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'confirmed')
        """,
        (reference, car["id"], customer_id, pickup.strftime(DATE_FMT),
         ret.strftime(DATE_FMT), branch, days, quote.base_total, quote.discount,
         quote.extras_total, quote.vat, quote.total,
         json.dumps([e["key"] for e in quote.extras])),
    )

    db.execute("UPDATE cars SET rental_count = rental_count + 1 WHERE id = ?", (car["id"],))

    return {
        "id": booking_id,
        "reference": reference,
        "car": car,
        "pickup_date": pickup.strftime(DATE_FMT),
        "return_date": ret.strftime(DATE_FMT),
        "pickup_branch": branch,
        "customer": {
            "full_name": payload["full_name"], "email": email,
            "phone": payload["phone"],
        },
        "quote": quote.to_dict(),
        "units_remaining": remaining - 1,
        "status": "confirmed",
    }


def get_booking(reference: str) -> dict | None:
    row = db.query(
        """
        SELECT b.*, c.slug, c.make, c.model, c.year, c.category, c.accent_hex,
               c.art_style, c.daily_rate, cu.full_name, cu.email, cu.phone
        FROM bookings b
        JOIN cars c      ON c.id = b.car_id
        JOIN customers cu ON cu.id = b.customer_id
        WHERE b.reference = ?
        """,
        (reference.strip().upper(),),
        one=True,
    )
    if row is None:
        return None
    data = dict(row)
    data["extras"] = [
        {"key": k, "label": EXTRAS[k]["label"]}
        for k in json.loads(data.get("extras") or "[]") if k in EXTRAS
    ]
    return data


def cancel_booking(reference: str) -> bool:
    booking = get_booking(reference)
    if booking is None or booking["status"] == "cancelled":
        return False
    db.execute("UPDATE bookings SET status = 'cancelled' WHERE reference = ?",
               (reference.strip().upper(),))
    return True


def log_search(query_text: str, payload: dict, top_slug: str) -> None:
    """Record a search so ranking can be reviewed later. Best-effort."""
    try:
        db.execute(
            "INSERT INTO search_events (query, payload, top_slug) VALUES (?,?,?)",
            (query_text[:500], json.dumps(payload)[:2000], top_slug),
        )
    except Exception:            # analytics must never break a user request
        pass
