import json
import sys
from pathlib import Path


def project_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


STATE_FILE = project_dir() / "runtime" / "listening_state.json"


def get_listening_muted(default: bool = False) -> bool:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return bool(data.get("muted", default))
    except Exception:
        return default


def set_listening_muted(muted: bool) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"muted": bool(muted)}, indent=2) + "\n",
        encoding="utf-8",
    )
