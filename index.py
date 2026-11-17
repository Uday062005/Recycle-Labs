"""Vercel entry point. Vercel looks for a top-level `app` in a root-level index.py and routes every path to it,
so no rewrite or functions block is needed (a rewrite would hand the app the path /api/index and cause a 404).
If the real app cannot start, a tiny fallback app returns the startup error instead of a blank 500."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "v2" / "website"))

try:
    import server_v2  # noqa: E402

    app = server_v2.app  # top-level `app` for Vercel's entrypoint detection
except Exception:  # pragma: no cover - only used on a broken deployment
    import traceback

    _tb = traceback.format_exc()

    def _ls(p):
        try:
            return sorted(os.listdir(p))
        except Exception as exc:
            return f"<cannot list: {exc}>"

    _info = ("ReSort failed to start.\n\n" + _tb + f"\nPython {sys.version}\nroot: {ROOT}\nroot files: {_ls(ROOT)}\n"
             f"v2: {_ls(ROOT / 'v2')}\nv2/website: {_ls(ROOT / 'v2' / 'website')}\nv2/data: {_ls(ROOT / 'v2' / 'data')}\n").encode()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": _info})
