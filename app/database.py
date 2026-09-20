"""SQLite persistence layer.

Uses the standard library only. A single connection is held per Flask
application context (``flask.g``) and closed automatically on teardown, which
keeps request handling thread-safe without an ORM.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from flask import current_app, g

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cars (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT    NOT NULL UNIQUE,
    make              TEXT    NOT NULL,
    model             TEXT    NOT NULL,
    year              INTEGER NOT NULL,
    category          TEXT    NOT NULL,
    body_style        TEXT    NOT NULL,
    transmission      TEXT    NOT NULL,
    fuel_type         TEXT    NOT NULL,
    seats             INTEGER NOT NULL,
    doors             INTEGER NOT NULL,
    luggage           INTEGER NOT NULL,
    horsepower        INTEGER NOT NULL,
    zero_to_hundred   REAL    NOT NULL,
    daily_rate        REAL    NOT NULL,
    deposit           REAL    NOT NULL,
    rating            REAL    NOT NULL DEFAULT 4.5,
    rental_count      INTEGER NOT NULL DEFAULT 0,
    total_units       INTEGER NOT NULL DEFAULT 1,
    color             TEXT    NOT NULL,
    accent_hex        TEXT    NOT NULL DEFAULT '#c9a227',
    art_style         TEXT    NOT NULL DEFAULT 'sedan',
    features          TEXT    NOT NULL DEFAULT '[]',
    tagline           TEXT    NOT NULL DEFAULT '',
    description       TEXT    NOT NULL DEFAULT '',
    is_active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL,
    phone       TEXT NOT NULL,
    licence_no  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reference     TEXT    NOT NULL UNIQUE,
    car_id        INTEGER NOT NULL REFERENCES cars(id) ON DELETE RESTRICT,
    customer_id   INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    pickup_date   TEXT    NOT NULL,
    return_date   TEXT    NOT NULL,
    pickup_branch TEXT    NOT NULL DEFAULT 'Dubai Marina',
    days          INTEGER NOT NULL,
    base_total    REAL    NOT NULL,
    discount      REAL    NOT NULL DEFAULT 0,
    extras_total  REAL    NOT NULL DEFAULT 0,
    vat           REAL    NOT NULL DEFAULT 0,
    total         REAL    NOT NULL,
    extras        TEXT    NOT NULL DEFAULT '[]',
    status        TEXT    NOT NULL DEFAULT 'confirmed',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bookings_car_dates
    ON bookings(car_id, pickup_date, return_date);
CREATE INDEX IF NOT EXISTS idx_cars_category ON cars(category);

CREATE TABLE IF NOT EXISTS search_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query       TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    top_slug    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_db() -> sqlite3.Connection:
    """Return the connection bound to the current application context."""
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DATABASE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exception: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql: str, params: Iterable[Any] = (), one: bool = False):
    cur = get_db().execute(sql, tuple(params))
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """Run a write statement and return the new row id."""
    conn = get_db()
    cur = conn.execute(sql, tuple(params))
    conn.commit()
    row_id = cur.lastrowid
    cur.close()
    return row_id


def init_db(force: bool = False) -> None:
    """Create the schema and seed the fleet if the database is empty."""
    from app.seed import seed_fleet  # imported late to avoid a cycle

    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()

    if force:
        conn.execute("DELETE FROM cars")
        conn.commit()

    count = conn.execute("SELECT COUNT(*) AS n FROM cars").fetchone()["n"]
    if count == 0:
        seed_fleet(conn)


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
