"""Config loading: real env > settings.json > .env. Never overrides real env."""

import json
import os
from pathlib import Path

from orchestrator.errors import OrchestratorError
from orchestrator.paths import user_data_dir

SETTINGS_KEYS = {
    "endpoint": "MOONSHOT_BASE_URL",
    "api_key": "MOONSHOT_API_KEY",
    "model": "MOONSHOT_MODEL",
}


def _parse_env_file(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def load_settings(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise OrchestratorError(f"settings file {p} is malformed: {e}") from e
    if not isinstance(data, dict):
        raise OrchestratorError(f"settings file {p} must contain a json object")
    return {k: v for k, v in data.items() if k in SETTINGS_KEYS}


def save_settings(path: str | Path, settings: dict) -> None:
    """Atomic write, owner-only permissions, unknown keys dropped."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in settings.items() if k in SETTINGS_KEYS and v}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def resolve_config(env_path: str | Path = ".env",
                   settings_path: Path | None = None) -> dict[str, str]:
    """.env first, settings.json overlaid on top (mapped through SETTINGS_KEYS)."""
    if settings_path is None:
        settings_path = user_data_dir() / "settings.json"
    cfg = _parse_env_file(Path(env_path))
    for key, value in load_settings(settings_path).items():
        cfg[SETTINGS_KEYS[key]] = value
    return cfg


def apply_config(cfg: dict[str, str]) -> None:
    """Real environment variables always win."""
    for key, value in cfg.items():
        os.environ.setdefault(key, value)


def load_env(path: str | Path = ".env", settings_path: Path | None = None) -> None:
    apply_config(resolve_config(path, settings_path))
