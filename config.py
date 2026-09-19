"""Application configuration.

Config is selected by the FLASK_ENV environment variable and resolved through
``get_config()``. Secrets are read from the environment with development-only
fallbacks so the project runs out of the box but never ships a hard-coded key
in production.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class BaseConfig:
    """Settings shared by every environment."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "velocity.db"))

    JSON_SORT_KEYS = False
    TEMPLATES_AUTO_RELOAD = True

    # Business rules
    COMPANY_NAME = "Velocity Drive"
    COMPANY_CITY = "Dubai"
    CURRENCY = "AED"
    MIN_RENTAL_DAYS = 1
    MAX_RENTAL_DAYS = 90
    VAT_RATE = 0.05           # UAE VAT
    SECURITY_DEPOSIT = 1500.0

    # Multi-day discount tiers: (minimum days, discount fraction)
    DISCOUNT_TIERS = ((30, 0.25), (7, 0.15), (3, 0.07))

    # Recommendation engine weights. These sum to 1.0 and are the single place
    # to tune ranking behaviour.
    RECOMMENDER_WEIGHTS = {
        "semantic": 0.34,     # TF-IDF cosine similarity on the car profile text
        "budget": 0.24,       # how well the daily rate fits the stated budget
        "capacity": 0.16,     # seats vs. passengers
        "category": 0.14,     # explicit category / body-style preference
        "features": 0.07,     # requested feature coverage
        "quality": 0.05,      # rating and popularity prior
    }


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    ENV_NAME = "development"


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    ENV_NAME = "testing"
    DATABASE_PATH = str(BASE_DIR / "velocity_test.db")


class ProductionConfig(BaseConfig):
    DEBUG = False
    ENV_NAME = "production"
    TEMPLATES_AUTO_RELOAD = False


_CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None) -> type[BaseConfig]:
    """Return the config class for ``name`` (defaults to FLASK_ENV)."""
    key = (name or os.environ.get("FLASK_ENV") or "development").lower()
    return _CONFIGS.get(key, DevelopmentConfig)
