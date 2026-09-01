"""Platform-standard per-user data directory for the desktop app."""

import os
import sys
from pathlib import Path

APP_NAME = "ex-co-model"


def user_data_dir() -> Path:
    """Where the app stores sessions, builds and settings. Does not create it."""
    override = os.environ.get("EXCO_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / APP_NAME
