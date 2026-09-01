import shutil
import sys
from pathlib import Path

import pytest

# The `orchestrator` package is pip-installed (editable) into the shared venv;
# `app` is a top-level package at the repo root, so put the root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

requires_blender = pytest.mark.skipif(
    shutil.which("blender") is None, reason="blender not on PATH"
)
