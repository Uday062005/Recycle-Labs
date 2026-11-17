import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "v2" / "website"))

from server_v2 import app  # noqa: F401
