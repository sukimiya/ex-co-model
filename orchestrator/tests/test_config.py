import os

from orchestrator.config import load_env


def test_load_env_sets_vars(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nMOONSHOT_API_KEY=sk-test\n\nMOONSHOT_MODEL=k3-256k\n",
                   encoding="utf-8")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_MODEL", raising=False)
    load_env(env)
    assert os.environ["MOONSHOT_API_KEY"] == "sk-test"
    assert os.environ["MOONSHOT_MODEL"] == "k3-256k"


def test_load_env_does_not_override_real_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("MOONSHOT_API_KEY=sk-from-file\n", encoding="utf-8")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-real")
    load_env(env)
    assert os.environ["MOONSHOT_API_KEY"] == "sk-real"


def test_load_env_missing_file_is_noop(tmp_path):
    load_env(tmp_path / "nope.env")  # must not raise
