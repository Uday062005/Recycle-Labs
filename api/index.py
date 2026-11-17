"""Vercel entry point: exposes the ReSort Starlette (ASGI) app as `app`.

If the app cannot start, a tiny fallback app returns the startup error and the files it can see, instead of Vercel's blank 500.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v2" / "website"))
from server_v2 import app
    _tb = traceback.format_exc()

    def _ls(p: Path):
        try:
            return sorted(os.listdir(p))
        except Exception as exc:
            return f"<cannot list: {exc}>"

    _info = (
        "ReSort failed to start.\n\n" + _tb
        + f"\nPython {sys.version}\nroot: {ROOT}\nroot files: {_ls(ROOT)}\nv2: {_ls(ROOT / 'v2')}\n"
        + f"v2/website: {_ls(ROOT / 'v2' / 'website')}\nv2/data: {_ls(ROOT / 'v2' / 'data')}\n"
    ).encode()

    async def app(scope, receive, send):  # noqa: F811
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": _info})
