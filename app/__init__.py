"""Application factory.

Wires the configuration, the database, the two blueprints (JSON API and
server-rendered pages), the shared template filters and the error handlers.

    from app import create_app
    app = create_app()

Error responses follow the surface they were requested from: anything under
``/api/`` gets JSON, everything else gets the rendered error page.
"""

from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from config import get_config

API_PREFIX = "/api/v1"


def _wants_json() -> bool:
    """True when the current request targets the JSON API."""
    return request.path.startswith(API_PREFIX) or request.path.startswith("/api/")


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    _register_filters(app)
    _register_blueprints(app)
    _register_error_handlers(app)

    from app import database

    database.init_app(app)

    # Build the schema, seed the fleet and index the corpus once per process.
    # Tests do this themselves against a temp database, so skip it there.
    if not app.config.get("TESTING"):
        with app.app_context():
            from app.recommender import build_index
            from app.services import load_fleet

            database.init_db()
            build_index(load_fleet(), app.config["RECOMMENDER_WEIGHTS"])

    return app


# --------------------------------------------------------------------------
# Template filters
# --------------------------------------------------------------------------

def _register_filters(app: Flask) -> None:
    @app.template_filter("money")
    def money(value) -> str:
        """1250.0 -> '1,250'. Prices are whole dirhams everywhere on screen."""
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return "0"

    @app.template_filter("money2")
    def money2(value) -> str:
        """As ``money`` but keeps fils, for totals that must reconcile."""
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return "0.00"


# --------------------------------------------------------------------------
# Blueprints
# --------------------------------------------------------------------------

def _register_blueprints(app: Flask) -> None:
    from app.api.routes import api_bp
    from app.web.routes import web_bp

    app.register_blueprint(api_bp, url_prefix=API_PREFIX)
    app.register_blueprint(web_bp)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

def _register_error_handlers(app: Flask) -> None:
    from app.services import ValidationError

    @app.errorhandler(ValidationError)
    def on_validation_error(err: ValidationError):
        """A broken business rule is a 400, never a 500."""
        if _wants_json():
            return jsonify(error="invalid_request", message=err.message,
                           field=err.field), 400
        return render_template("error.html", code=400, message=err.message), 400

    @app.errorhandler(404)
    def on_not_found(_err):
        if _wants_json():
            return jsonify(error="not_found",
                           message="No such resource."), 404
        return render_template("error.html", code=404,
                               message="We couldn't find that page."), 404

    @app.errorhandler(500)
    def on_server_error(_err):
        if _wants_json():
            return jsonify(error="server_error",
                           message="Something went wrong."), 500
        return render_template("error.html", code=500,
                               message="Something went wrong at our end."), 500
