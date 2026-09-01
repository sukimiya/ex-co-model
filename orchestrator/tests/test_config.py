import json
import os

import pytest

from orchestrator.config import (apply_config, load_env, load_settings,
                                 resolve_config, save_settings)
from orchestrator.errors import OrchestratorError


def test_load_env_sets_vars(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nMOONSHOT_API_KEY=sk-test\n\nMOONSHOT_MODEL=k3-256k\n",
                   encoding="utf-8")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_MODEL", raising=False)
    load_env(env, settings_path=tmp_path / "none.json")
    assert os.environ["MOONSHOT_API_KEY"] == "sk-test"
    assert os.environ["MOONSHOT_MODEL"] == "k3-256k"


def test_load_env_does_not_override_real_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("MOONSHOT_API_KEY=sk-from-file\n", encoding="utf-8")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-real")
    load_env(env, settings_path=tmp_path / "none.json")
    assert os.environ["MOONSHOT_API_KEY"] == "sk-real"


def test_load_env_missing_file_is_noop(tmp_path):
    load_env(tmp_path / "nope.env", settings_path=tmp_path / "none.json")  # must not raise


def test_resolve_config_settings_beat_dotenv(tmp_path):
    (tmp_path / ".env").write_text("MOONSHOT_BASE_URL=https://env.example/v1\n", encoding="utf-8")
    settings = tmp_path / "settings.json"
    save_settings(settings, {"endpoint": "https://settings.example/v1", "api_key": "sk-x"})
    cfg = resolve_config(tmp_path / ".env", settings)
    assert cfg["MOONSHOT_BASE_URL"] == "https://settings.example/v1"
    assert cfg["MOONSHOT_API_KEY"] == "sk-x"


def test_apply_config_real_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "real-env-key")
    apply_config({"MOONSHOT_API_KEY": "from-file"})
    assert os.environ["MOONSHOT_API_KEY"] == "real-env-key"


def test_save_settings_permissions_and_filter(tmp_path):
    p = tmp_path / "settings.json"
    save_settings(p, {"endpoint": "https://x/v1", "hacker": "drop me"})
    assert (p.stat().st_mode & 0o777) == 0o600
    assert json.loads(p.read_text()) == {"endpoint": "https://x/v1"}


def test_load_settings_missing_returns_empty(tmp_path):
    assert load_settings(tmp_path / "nope.json") == {}


def test_load_settings_malformed_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(OrchestratorError):
        load_settings(p)
