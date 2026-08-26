"""Minimal .env loading (KEY=VALUE lines). Real env vars always win."""

import os
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    """Load variables from a .env file into os.environ (no override)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
