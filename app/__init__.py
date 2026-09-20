"""Application factory.

    from app import create_app
    app = create_app()              # FLASK_ENV, else development
    app = create_app("testing")

This module was empty in the repository as checked out — the package's
``create_app`` had been lost, so ``run.py`` and the test suite could not import
anything and the app would not start. It is reconstructed here from what the
rest of the package requires of it: the config classes in ``app.config``, the
per-request connection wiring in ``app.database``, the ``web`` blueprint in
``app.routes``, the ``api`` blueprint in ``app.api``, and the ``money`` and
``money2`` template filters the templates call.
"""

from __future__ import annotations

import os

from flask import Flask, render_template

from app.config import get_config


def _format_money(value: object, places: int) -> str:
    """Group thousands with a comma and fix the decimal places.

    Returns the input unchanged if it is not a number, so a template calling
    the filter on a missing value renders something visible rather than raising
    mid-response.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "" if value is None else str(value)
    return f"{number:,.{places}f}"


def register_filters(app: Flask) -> None:
    """Template filters used by the templates.

    ``money`` is for headline prices, which are whole dirhams, and ``money2``
    for anything itemised — a quote's VAT, discount and total all carry two
    decimal places from ``Quote.to_dict``.
    """
    app.add_template_filter(lambda v: _format_money(v, 0), "money")
    app.add_template_filter(lambda v: _format_money(v, 2), "money2")


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(error):  # noqa: ANN001
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(error):  # noqa: ANN001
        return render_template("error.html", code=500, message="Something went wrong"), 500


def create_app(config_name: str | None = None) -> Flask:
    """Build and configure the application."""
    # static/ sits at the repository root, in public/, because the Cloudflare
    # Worker serves the same files through its assets binding and that binding's
    # directory root becomes the URL root. Keeping it out of app/ means the
    # Worker can expose public/ without also publishing the templates.
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "static"),
    )
    app.config.from_object(get_config(config_name))

    # SECRET_KEY has a development fallback in config.py so the app runs out of
    # the box; refuse to start with it in production rather than signing
    # sessions with a published key.
    if not app.config.get("DEBUG") and not app.config.get("TESTING"):
        if app.config.get("SECRET_KEY") == "dev-only-change-me":
            if os.environ.get("FLASK_ENV") == "production":
                raise RuntimeError(
                    "SECRET_KEY is still the development default. "
                    "Set the SECRET_KEY environment variable before running in production."
                )

    # Imported here rather than at module scope: app.database and app.routes
    # both import from this package, so importing them at the top would form a
    # cycle through `from app import database`.
    from app import database
    from app.api import api_bp
    from app.routes import web_bp

    database.init_app(app)
    register_filters(app)
    register_error_handlers(app)

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Create the schema and seed the fleet."""
        from app.database import init_db

        init_db()
        print("Database ready.")

    return app
