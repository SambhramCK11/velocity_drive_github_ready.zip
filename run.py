"""Development entry point.

    python run.py            # http://127.0.0.1:5000
    PORT=8080 python run.py
"""

from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=app.config.get("DEBUG", False))
