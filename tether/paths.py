"""Where Tether keeps its data. Set TETHER_DATA_DIR to use another folder (tests do)."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    return Path(os.environ.get("TETHER_DATA_DIR") or PROJECT_ROOT / "data")
