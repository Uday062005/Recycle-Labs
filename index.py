"""TEMPORARY diagnostic entry point (stdlib only): reports the Python version, installed packages and whether each import works,
using subprocesses so that a native crash (e.g. in numpy) cannot kill the function. Replaced by the real entry point afterwards."""
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

STAMP = "diag-1"
ROOT = Path(__file__).resolve().parent


def _run(code, timeout=60):
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        return f"rc={r.returncode}\nstdout: {r.stdout.strip()[:600]}\nstderr: {r.stderr.strip()[-1500:]}"
    except Exception as exc:
        return f"<failed: {exc!r}>"


def _report():
    out = [f"stamp {STAMP}", f"python {sys.version}", f"executable {sys.executable}", f"root {ROOT}"]
    try:
        out.append("root files: " + str(sorted(os.listdir(ROOT))))
        out.append("v2: " + str(sorted(os.listdir(ROOT / "v2"))))
        out.append("v2/data: " + str(sorted(os.listdir(ROOT / "v2" / "data"))))
    except Exception as exc:
        out.append(f"<ls failed {exc!r}>")
    try:
        pk = sorted(f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions())
        out.append("packages: " + ", ".join(pk))
    except Exception as exc:
        out.append(f"<packages failed {exc!r}>")
    out.append("--- import numpy\n" + _run("import numpy; print(numpy.__version__)"))
    out.append("--- import starlette\n" + _run("import starlette; print(starlette.__version__)"))
    out.append("--- import server_v2\n" + _run("import sys; sys.path.insert(0, 'v2/website'); import server_v2; print('server ok', type(server_v2.app).__name__)"))
    return "\n".join(out).encode()


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    body = _report()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
    await send({"type": "http.response.body", "body": body})
