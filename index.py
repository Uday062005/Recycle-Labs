"""Vercel entry point. Vercel looks for a top-level `app` in a root-level index.py and routes every path to it,
so no rewrite or functions block is needed (a rewrite would hand the app the path /api/index and cause a 404)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "v2" / "website"))

import server_v2  # noqa: E402

app = server_v2.app  # top-level `app` for Vercel's entrypoint detection
