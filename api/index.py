"""Vercel serverless entrypoint.

Vercel turns each file under ``api/`` into a Python serverless function and
serves the WSGI callable it finds named ``app``. ``vercel.json`` rewrites every
path here, so Flask does its own routing — pages, the JSON API and /static —
exactly as it does under ``python run.py``.

This deliberately avoids Vercel's Flask framework detection, which probes a
fixed list of root filenames (app.py, index.py, server.py, main.py) that this
project does not use. The rewrite makes the entrypoint explicit instead.
"""

from __future__ import annotations

import os
import sys

# The function is bundled with the repository root one directory up. Put it on
# sys.path so `app` and `config` resolve the same way they do locally.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app  # noqa: E402

app = create_app()
