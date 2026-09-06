import json
import os
import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = base_dir()
ENV_FILE = BASE_DIR / ".env"
LEGACY_JSON_FILE = BASE_DIR / "config" / "api_keys.json"


KEY_ALIASES = {
    "GEMINI_API_KEY": "gemini_api_key",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "ZERNIO_API_KEY": "zernio_api_key",
    "HOME_ASSISTANT_URL": "home_assistant_url",
    "HOME_ASSISTANT_TOKEN": "home_assistant_token",
    "OS_SYSTEM": "os_system",
}


def _parse_env_file(path: Path = ENV_FILE) -> dict:
    data = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        data[key] = value
    return data


def _load_legacy_json() -> dict:
    if not LEGACY_JSON_FILE.exists():
        return {}
    try:
        return json.loads(LEGACY_JSON_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def get_config() -> dict:
    config = {}
    legacy = _load_legacy_json()
    for env_key, legacy_key in KEY_ALIASES.items():
        if legacy.get(legacy_key):
            config[env_key] = str(legacy[legacy_key]).strip()

    env_file = _parse_env_file()
    config.update({k: v for k, v in env_file.items() if v})

    for env_key in KEY_ALIASES:
        if os.getenv(env_key):
            config[env_key] = os.environ[env_key].strip()

    return config


def get_secret(name: str, default: str = "") -> str:
    return str(get_config().get(name, default) or "").strip()


def require_secret(name: str) -> str:
    value = get_secret(name)
    if not value:
        raise RuntimeError(f"{name} is not configured. Create a .env file from .env.example.")
    return value


def write_env(gemini_api_key: str, openrouter_api_key: str, zernio_api_key: str = "") -> None:
    existing = _parse_env_file()
    lines = [
        f"GEMINI_API_KEY={gemini_api_key.strip()}",
        f"OPENROUTER_API_KEY={openrouter_api_key.strip()}",
    ]
    if zernio_api_key.strip():
        lines.append(f"ZERNIO_API_KEY={zernio_api_key.strip()}")
    elif existing.get("ZERNIO_API_KEY"):
        lines.append(f"ZERNIO_API_KEY={existing['ZERNIO_API_KEY']}")

    for key in ("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN"):
        if existing.get(key):
            lines.append(f"{key}={existing[key]}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_configured() -> bool:
    return bool(get_secret("GEMINI_API_KEY") and get_secret("OPENROUTER_API_KEY"))
