import sys
from pathlib import Path

import pytest

from orchestrator.paths import user_data_dir


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("EXCO_DATA_DIR", str(tmp_path / "custom"))
    assert user_data_dir() == tmp_path / "custom"


def test_macos_default(monkeypatch):
    monkeypatch.delenv("EXCO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert user_data_dir() == Path.home() / "Library" / "Application Support" / "ex-co-model"


def test_windows_default(monkeypatch, tmp_path):
    monkeypatch.delenv("EXCO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert user_data_dir() == tmp_path / "ex-co-model"


def test_linux_default(monkeypatch, tmp_path):
    monkeypatch.delenv("EXCO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert user_data_dir() == tmp_path / "ex-co-model"
