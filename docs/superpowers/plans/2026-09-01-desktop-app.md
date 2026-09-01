# Desktop App (Sub-project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ex-co-model into a distributable desktop app (Windows + macOS): native window via pywebview, PyInstaller onedir packaging, bundled portable Blender, BYOK settings UI.

**Architecture:** All existing code (kernel / orchestrator / web UI) is reused unchanged in behavior. New: platform user-data-dir resolution, a Blender discovery chain (env → bundled → PATH), a settings.json config layer (env > settings.json > .env), `/api/settings` endpoints + settings UI, and a thin `app/` pywebview shell with a scriptable `--smoke` mode for headless acceptance.

**Spec:** `docs/superpowers/specs/2026-08-27-desktop-app-design.md`

**Tech Stack:** Python 3.14, pydantic v2, pytest, pywebview, PyInstaller (onedir), Blender 5.2.1 portable.

## Global Constraints

- Repo root: `/Users/breannalinlin/code/Github/ex-co-model`. Work directly on `main`.
- Test commands: `cd kernel && .venv/bin/pytest` and `cd orchestrator && ../kernel/.venv/bin/pytest` (shared venv at `kernel/.venv`). Do NOT recreate the venv.
- New third-party deps are allowed ONLY in `app/requirements-app.txt` (pywebview, pyinstaller). `kernel` and `orchestrator` runtime dependencies stay as-is (orchestrator: `openai>=1.0` only — never add `optree`, PyPI name collision).
- Code identifiers/comments/commit messages in English (conventional commits). User-facing UI strings in Chinese. Docs in Chinese.
- CLI behavior must not change: default session `./.exco/session.json`, workdir `./.exco/build`, Blender from PATH. All new behavior activates via env vars or app entry point.
- Commit at the end of every task. Push after the final task.
- Blender binary for bundling: pinned version 5.2.1, downloaded from `https://download.blender.org/release/Blender5.2/`.

---

### Task 1: user data directory resolution

**Files:**
- Create: `orchestrator/orchestrator/paths.py`
- Test: `orchestrator/tests/test_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `user_data_dir() -> Path` — env override `EXCO_DATA_DIR` first; then `%APPDATA%/ex-co-model` (win32), `~/Library/Application Support/ex-co-model` (darwin), `$XDG_DATA_HOME/ex-co-model` or `~/.local/share/ex-co-model` (other). Does NOT create the directory.

> Plan note: the spec sketch says `app/paths.py`; it lives in `orchestrator` instead because `config.py` (Task 3) needs it and the orchestrator must not depend on the app shell.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_paths.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.paths`)

- [ ] **Step 3: Implement paths.py**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_paths.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator/paths.py orchestrator/tests/test_paths.py
git commit -m "feat(orchestrator): platform user data directory resolution"
```

---

### Task 2: Blender discovery chain (kernel)

**Files:**
- Modify: `kernel/optree/blender_session.py` (find_blender + use it)
- Test: `kernel/tests/test_blender_session.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `find_blender() -> str | None` — lookup order: `EXCO_BLENDER` env var (must exist) → PyInstaller-bundled Blender → `shutil.which("blender")`. `blender_available()` and `run_blender_script()` must use it.

- [ ] **Step 1: Write the failing tests**

Append to `kernel/tests/test_blender_session.py` (read the file first, match its import style):

```python
def test_find_blender_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "blender"
    fake.touch()
    monkeypatch.setenv("EXCO_BLENDER", str(fake))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert find_blender() == str(fake)


def test_find_blender_env_override_missing_file_ignored(monkeypatch):
    monkeypatch.setenv("EXCO_BLENDER", "/nonexistent/blender")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/blender")
    assert find_blender() == "/usr/bin/blender"


def test_find_blender_bundled(monkeypatch, tmp_path):
    monkeypatch.delenv("EXCO_BLENDER", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ExCoModel"))
    bundled = tmp_path / "blender" / "blender.exe"
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert find_blender() == str(bundled)


def test_find_blender_path_fallback(monkeypatch):
    monkeypatch.delenv("EXCO_BLENDER", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/homebrew/bin/blender")
    assert find_blender() == "/opt/homebrew/bin/blender"


def test_find_blender_none(monkeypatch):
    monkeypatch.delenv("EXCO_BLENDER", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert find_blender() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd kernel && .venv/bin/pytest tests/test_blender_session.py -k find_blender -v`
Expected: FAIL (`ImportError: cannot import name 'find_blender'`)

- [ ] **Step 3: Implement find_blender**

In `kernel/optree/blender_session.py`, add `import os, sys` and:

```python
def _bundled_blender() -> Path | None:
    """Blender shipped inside a PyInstaller bundle, next to the executable."""
    if not getattr(sys, "frozen", False):
        return None
    root = Path(sys.executable).resolve().parent
    candidates = [
        root / "blender" / "blender.exe",                                  # windows
        root / "blender" / "blender",                                      # linux
        root / "blender" / "Blender.app" / "Contents" / "MacOS" / "Blender",  # mac onedir
        root.parent / "Resources" / "blender" / "Blender.app" / "Contents" / "MacOS" / "Blender",  # mac .app
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_blender() -> str | None:
    """Lookup order: EXCO_BLENDER env -> bundled (PyInstaller) -> PATH."""
    override = os.environ.get("EXCO_BLENDER")
    if override and Path(override).exists():
        return override
    bundled = _bundled_blender()
    if bundled is not None:
        return str(bundled)
    return shutil.which("blender")
```

Change `blender_available()` to `return find_blender() is not None`. In `run_blender_script`, replace the availability guard and the command:

```python
    exe = find_blender()
    if exe is None:
        raise BlenderError(
            "blender not found; set EXCO_BLENDER or install Blender >= 4.0"
        )
```

and `"args[0]": exe` — i.e. the subprocess list becomes `[exe, "-b", "--factory-startup", "--python", str(runner_path)]`.

- [ ] **Step 4: Run all kernel tests**

Run: `cd kernel && .venv/bin/pytest`
Expected: all PASS (59 existing + 5 new). The existing real-Blender tests must still pass — they now go through `find_blender()` and hit the PATH fallback on the dev machine.

- [ ] **Step 5: Commit**

```bash
git add kernel/optree/blender_session.py kernel/tests/test_blender_session.py
git commit -m "feat(kernel): blender discovery chain (env, bundled, PATH)"
```

---

### Task 3: settings.json config layer

**Files:**
- Modify: `orchestrator/orchestrator/config.py`
- Test: `orchestrator/tests/test_config.py`

**Interfaces:**
- Consumes: `orchestrator.paths.user_data_dir()` (Task 1).
- Produces:
  - `SETTINGS_KEYS = {"endpoint": "MOONSHOT_BASE_URL", "api_key": "MOONSHOT_API_KEY", "model": "MOONSHOT_MODEL"}`
  - `load_settings(path: Path) -> dict` — read settings.json; `{}` when missing; raises `OrchestratorError` on malformed JSON.
  - `save_settings(path: Path, settings: dict) -> None` — atomic write, chmod 600, only `SETTINGS_KEYS` keys are kept.
  - `resolve_config(env_path: str | Path = ".env", settings_path: Path | None = None) -> dict[str, str]` — parse .env, then overlay settings.json mapped through SETTINGS_KEYS (settings wins). Default settings_path is `user_data_dir() / "settings.json"`.
  - `apply_config(cfg: dict[str, str]) -> None` — `os.environ.setdefault` each (real env always wins).
  - `load_env(path=".env", settings_path=None)` — existing signature extended; now calls `apply_config(resolve_config(path, settings_path))`. Existing callers (`cli.main`, tests) keep working unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/tests/test_config.py` (read it first, match its style):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL (new names don't exist)

- [ ] **Step 3: Implement**

Replace the body of `orchestrator/orchestrator/config.py` with:

```python
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
```

- [ ] **Step 4: Run all orchestrator tests**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest`
Expected: all PASS (68 existing + 5 new). Watch for existing tests that relied on `load_env` setdefault-only behavior — semantics are unchanged for real env vars.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator/config.py orchestrator/tests/test_config.py
git commit -m "feat(orchestrator): settings.json config layer with precedence env > settings > .env"
```

---

### Task 4: /api/settings endpoints + settings UI

**Files:**
- Modify: `orchestrator/orchestrator/server.py` (GET/POST /api/settings, settings_path on _State)
- Modify: `orchestrator/orchestrator/static/index.html` (settings section)
- Modify: `orchestrator/orchestrator/cli.py:36` (serve passes settings_path — default None is fine)
- Test: `orchestrator/tests/test_server.py`

**Interfaces:**
- Consumes: `config.load_settings/save_settings`, `config.SETTINGS_KEYS`, `paths.user_data_dir` (Task 1+3).
- Produces:
  - `GET /api/settings` → `{"endpoint": str, "model": str, "has_key": bool, "presets": [{"label": str, "endpoint": str, "model": str}, ...]}`. The API key is NEVER returned.
  - `POST /api/settings` body `{"endpoint": str, "model": str, "api_key": str}` → saves settings.json and sets the three `MOONSHOT_*` env vars in the running process (direct assignment, overriding). Empty `api_key` keeps the stored one. Response `{"ok": true}` or `{"ok": false, "error": ...}`.
  - `make_server(..., settings_path: Path | None = None)` — default `user_data_dir() / "settings.json"`.

Presets (exact values):

```python
PRESETS = [
    {"label": "Kimi Code", "endpoint": "https://api.kimi.com/coding/v1", "model": "kimi-for-coding"},
    {"label": "Kimi (Moonshot)", "endpoint": "https://api.moonshot.ai/v1", "model": "kimi-k2-0711-preview"},
    {"label": "DeepSeek", "endpoint": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"label": "OpenAI", "endpoint": "https://api.openai.com/v1", "model": "gpt-4o"},
]
```

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/tests/test_server.py` (read it first, reuse its fixture/_get/_post helpers and tmp paths):

```python
def test_get_settings_hides_key(server):  # adapt fixture name to the file's
    r = _get(server, "/api/settings")
    assert r.status == 200
    data = json.loads(r.read())
    assert "api_key" not in data
    assert data["has_key"] is False
    assert any(p["label"] == "Kimi Code" for p in data["presets"])


def test_post_settings_saves_and_hides(server, tmp_path, monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    r = _post(server, "/api/settings",
              {"endpoint": "https://x/v1", "model": "m1", "api_key": "sk-secret"})
    assert json.loads(r.read())["ok"] is True
    r = _get(server, "/api/settings")
    body = r.read().decode()
    data = json.loads(body)
    assert data["endpoint"] == "https://x/v1"
    assert data["model"] == "m1"
    assert data["has_key"] is True
    assert "sk-secret" not in body  # key never serialized
    import os
    assert os.environ["MOONSHOT_API_KEY"] == "sk-secret"
```

(Adapt to the test file's actual fixtures; the file already boots a real HTTP server on an ephemeral port — pass `settings_path=tmp_path / "settings.json"` when constructing it. If the existing fixture doesn't allow extra kwargs, add a local fixture in the same style.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_server.py -k settings -v`
Expected: FAIL (404 on /api/settings)

- [ ] **Step 3: Server implementation**

In `server.py`: import `from orchestrator.config import load_settings, save_settings` and `from orchestrator.paths import user_data_dir`. Add to `_State.__init__` a `settings_path` param (keyword, default `None` → resolved lazily to `user_data_dir() / "settings.json"`). Thread it through `make_server(..., settings_path=None)` and `serve(..., settings_path=None)`.

Add to `do_GET`:

```python
            elif self.path == "/api/settings":
                s = load_settings(state.settings_path())
                self._send_json(200, {
                    "endpoint": s.get("endpoint", ""),
                    "model": s.get("model", ""),
                    "has_key": bool(s.get("api_key")),
                    "presets": PRESETS,
                })
```

Add to `do_POST` (before the `/api/apply` 404 guard):

```python
            if self.path == "/api/settings":
                try:
                    payload = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"])))
                    current = load_settings(state.settings_path())
                    if payload.get("api_key"):
                        current["api_key"] = payload["api_key"]
                    current["endpoint"] = payload.get("endpoint", current.get("endpoint", ""))
                    current["model"] = payload.get("model", current.get("model", ""))
                    save_settings(state.settings_path(), current)
                    import os
                    from orchestrator.config import SETTINGS_KEYS
                    for k, v in current.items():
                        if v:
                            os.environ[SETTINGS_KEYS[k]] = v
                    self._send_json(200, {"ok": True})
                except (OrchestratorError, json.JSONDecodeError,
                        ValueError, TypeError, KeyError) as e:
                    self._send_json(200, {"ok": False, "error": str(e)})
                return
            if self.path != "/api/apply":
```

Define `PRESETS` at module level (values above).

- [ ] **Step 4: UI settings section**

In `static/index.html`, in the `#side` div after the OpTree `<pre>` block add:

```html
  <h3>设置（BYOK）</h3>
  <select id="preset"></select>
  <input id="cfg-endpoint" placeholder="endpoint，如 https://api.moonshot.ai/v1">
  <input id="cfg-model" placeholder="model，如 kimi-k2-0711-preview">
  <input id="cfg-key" type="password" placeholder="API key（留空 = 不修改）">
  <button id="cfg-save">保存设置</button>
```

Add CSS: `input, select { background: #222; color: #ddd; border: 1px solid #444; padding: 6px; }`.

JS additions:

```js
async function loadSettings() {
  const s = await (await fetch("/api/settings")).json();
  document.getElementById("cfg-endpoint").value = s.endpoint || "";
  document.getElementById("cfg-model").value = s.model || "";
  const sel = document.getElementById("preset");
  sel.innerHTML = '<option value="">预设…</option>';
  for (const p of s.presets) {
    const o = document.createElement("option");
    o.textContent = p.label;
    o.value = p.endpoint + "|" + p.model;
    sel.appendChild(o);
  }
  sel.onchange = () => {
    if (!sel.value) return;
    const [ep, m] = sel.value.split("|");
    document.getElementById("cfg-endpoint").value = ep;
    document.getElementById("cfg-model").value = m;
  };
}
document.getElementById("cfg-save").onclick = async () => {
  const body = {
    endpoint: document.getElementById("cfg-endpoint").value.trim(),
    model: document.getElementById("cfg-model").value.trim(),
    api_key: document.getElementById("cfg-key").value.trim(),
  };
  const r = await (await fetch("/api/settings", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })).json();
  document.getElementById("status").textContent = r.ok ? "设置已保存" : "保存失败：" + r.error;
  if (r.ok) document.getElementById("cfg-key").value = "";
};
loadSettings();
```

And in the `go` onclick error branch, when the error mentions `MOONSHOT_API_KEY`, append `"（请先在下方设置里填 API key）"`:

```js
      status.textContent = "失败：" + r.error +
        (String(r.error).includes("MOONSHOT_API_KEY") ? "（请先在下方设置里填 API key）" : "");
```

- [ ] **Step 5: Run all orchestrator tests**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/orchestrator/server.py orchestrator/orchestrator/static/index.html orchestrator/tests/test_server.py
git commit -m "feat(ui): BYOK settings endpoint and settings panel"
```

---

### Task 5: app shell (pywebview) + smoke mode

**Files:**
- Create: `app/__init__.py` (empty)
- Create: `app/main.py`
- Create: `app/requirements-app.txt`
- Test: `orchestrator/tests/test_app_shell.py`

**Interfaces:**
- Consumes: `orchestrator.server.make_server`, `orchestrator.paths.user_data_dir`, `orchestrator.config.load_env`.
- Produces:
  - `app.main.free_port() -> int`
  - `app.main.main(argv: list[str] | None = None) -> int` — args: `--smoke` (no window; boot server, GET /api/state, print `SMOKE OK`, return 0), `--data-dir PATH` (sets EXCO_DATA_DIR before anything else). Desktop mode: starts `make_server` on a daemon thread at 127.0.0.1:free_port, opens pywebview window titled `ex-co-model`, `webview.start()`, returns 0 on window close.
  - Data layout under data dir: `<data>/session.json`, `<data>/build/`, settings at `<data>/settings.json` (via Task 3 default).
  - `app/requirements-app.txt`: exactly `pywebview>=5.0` and `pyinstaller>=6.0`.

- [ ] **Step 1: Write the failing test**

`orchestrator/tests/test_app_shell.py` (tests import `app.main`; add repo root to sys.path via the existing conftest pattern — read `orchestrator/tests/conftest.py` first and follow how it makes `orchestrator` importable; `app` is a top-level package at repo root, same trick):

```python
import json
import urllib.request

from app.main import free_port, main


def test_free_port_returns_bindable_port():
    import socket
    p = free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", p))


def test_smoke_mode(tmp_path, capsys):
    rc = main(["--smoke", "--data-dir", str(tmp_path)])
    assert rc == 0
    assert "SMOKE OK" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_app_shell.py -v`
Expected: FAIL (`ModuleNotFoundError: app`)

- [ ] **Step 3: Implement app/main.py**

```python
"""Desktop shell: serve the orchestrator UI on localhost and show it in a
native window (pywebview). --smoke boots the server without a window."""

import argparse
import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ex-co-model")
    parser.add_argument("--smoke", action="store_true",
                        help="boot the server, check /api/state, exit")
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        os.environ["EXCO_DATA_DIR"] = str(args.data_dir)

    from orchestrator.config import load_env
    from orchestrator.paths import user_data_dir
    from orchestrator.server import make_server

    load_env()  # .env in cwd if present; settings.json under data dir
    data = user_data_dir()
    (data / "build").mkdir(parents=True, exist_ok=True)
    port = free_port()
    from orchestrator.llm import MoonshotClient
    server = make_server(
        data / "session.json",       # session file inside the data dir
        data / "build",              # workdir inside the data dir
        Path("parts") if Path("parts").exists() else None,  # dev convenience
        MoonshotClient,              # llm_factory (constructed lazily per request)
        host="127.0.0.1", port=port,
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"

    if args.smoke:
        for _ in range(50):
            try:
                with urllib.request.urlopen(url + "/api/state", timeout=2) as r:
                    json.loads(r.read())
                break
            except OSError:
                time.sleep(0.1)
        else:
            print("SMOKE FAIL: server did not respond")
            return 1
        print("SMOKE OK")
        server.shutdown()
        return 0

    import webview  # imported lazily: --smoke works without pywebview installed
    webview.create_window("ex-co-model", url, width=1400, height=900)
    webview.start()
    server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`app/__init__.py` is empty. `app/requirements-app.txt`:

```
pywebview>=5.0
pyinstaller>=6.0
```

- [ ] **Step 4: Run tests**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_app_shell.py -v`
Expected: 2 PASS (pywebview must NOT be required for these tests — that's why the import is lazy).

Then the full suite: `cd orchestrator && ../kernel/.venv/bin/pytest` — all PASS.

Manual smoke: `kernel/.venv/bin/python -m app.main --smoke` from repo root → `SMOKE OK`.

- [ ] **Step 5: Commit**

```bash
git add app/ orchestrator/tests/test_app_shell.py
git commit -m "feat(app): pywebview desktop shell with --smoke mode"
```

---

### Task 6: build scripts + macOS packaging acceptance

**Files:**
- Create: `scripts/build_app.sh` (macOS)
- Create: `scripts/build_app.ps1` (Windows; written now, executed later on the Windows machine)
- Create: `app/THIRD_PARTY_NOTICES.md`

**Interfaces:**
- Consumes: `app/main.py` entry, `find_blender()` bundled-candidates from Task 2 (`<exe dir>/blender/...` and mac `.app` Resources variant).
- Produces: `dist/ExCoModel.app` (macOS) / `dist/ExCoModel/` (Windows), each with bundled Blender such that `find_blender()` finds it with no system Blender and no env vars.

- [ ] **Step 1: Write scripts/build_app.sh**

```bash
#!/bin/bash
# Build ExCoModel.app (macOS). Run from repo root. Requires: curl, python3.14.
set -euo pipefail

BLENDER_VERSION=5.2.1
BLENDER_DMG="blender-${BLENDER_VERSION}-macos-arm64.dmg"
BLENDER_URL="https://download.blender.org/release/Blender5.2/${BLENDER_DMG}"
BUILD=.build-app
VENV="$BUILD/venv"

rm -rf "$BUILD" dist/ExCoModel.app
mkdir -p "$BUILD"

# 1. build venv with app deps
python3.14 -m venv "$VENV"
"$VENV/bin/pip" install --quiet ./kernel ./orchestrator -r app/requirements-app.txt

# 2. fetch portable Blender
if [ ! -f "$BUILD/$BLENDER_DMG" ]; then
  curl -L "$BLENDER_URL" -o "$BUILD/$BLENDER_DMG"
fi
hdiutil attach -nobrowse -mountpoint "$BUILD/mnt" "$BUILD/$BLENDER_DMG"
mkdir -p "$BUILD/blender"
cp -R "$BUILD/mnt/Blender.app" "$BUILD/blender/Blender.app"
hdiutil detach "$BUILD/mnt"

# 3. pyinstaller onedir .app
"$VENV/bin/pyinstaller" --noconfirm --clean --onedir --windowed \
  --name ExCoModel \
  --add-data "orchestrator/orchestrator/static:orchestrator/static" \
  app/main.py

# 4. drop Blender where find_blender() looks: Contents/MacOS/blender/Blender.app
mkdir -p dist/ExCoModel.app/Contents/MacOS/blender
cp -R "$BUILD/blender/Blender.app" dist/ExCoModel.app/Contents/MacOS/blender/Blender.app

# 5. third-party notices
cp app/THIRD_PARTY_NOTICES.md dist/ExCoModel.app/Contents/MacOS/
if [ -f "$BUILD/blender/Blender.app/Contents/Resources/LICENSE" ]; then
  cp "$BUILD/blender/Blender.app/Contents/Resources/LICENSE" \
     dist/ExCoModel.app/Contents/MacOS/BLENDER-LICENSE.txt
fi

echo "built: dist/ExCoModel.app"
```

- [ ] **Step 2: Write scripts/build_app.ps1**

Same flow for Windows: `.build-app\venv` (`py -3.14 -m venv`), pip install `./kernel ./orchestrator -r app\requirements-app.txt`, download `blender-5.2.1-windows-x64.zip` from `https://download.blender.org/release/Blender5.2/`, `Expand-Archive` to `.build-app\blender`, pyinstaller `--onedir --windowed --name ExCoModel --add-data "orchestrator/orchestrator/static;orchestrator/static" app/main.py` (note: PyInstaller `--add-data` separator on Windows is `;`), then copy `.build-app\blender\blender-5.2.1-windows-x64` → `dist\ExCoModel\blender` so that `dist\ExCoModel\blender\blender.exe` exists (matching the Task-2 candidate), copy THIRD_PARTY_NOTICES.md and Blender license. Write it fully, mirroring the bash script step by step; it will be executed on the Windows machine later.

- [ ] **Step 3: Write app/THIRD_PARTY_NOTICES.md**

```markdown
# Third-Party Notices

This application bundles Blender (https://www.blender.org), which is free
software licensed under the GNU General Public License v2 or later.
Blender is distributed unmodified as a separate program invoked via its
command-line interface. Its complete license text ships alongside this
notice (BLENDER-LICENSE.txt); source code is available at
https://www.blender.org/download/ and https://projects.blender.org/blender/blender.

This application also uses pywebview (BSD-3-Clause), PyInstaller (GPL with
bootloader exception), and three.js (MIT).
```

- [ ] **Step 4: Run the macOS build and acceptance**

```bash
bash scripts/build_app.sh
```

Expected: `built: dist/ExCoModel.app`. Then the packaged-app smoke, simulating a clean machine (no EXCO_BLENDER, no blender on PATH for this invocation):

```bash
env -u EXCO_BLENDER PATH=/usr/bin:/bin dist/ExCoModel.app/Contents/MacOS/ExCoModel --smoke --data-dir /tmp/exco-accept
```

Expected: `SMOKE OK`, and `/tmp/exco-accept/build/` exists. This single run exercises the full discovery chain: settings from the data dir, server boot, and (implicitly) that the bundled Blender is discoverable — the hard requirement is SMOKE OK with no system Blender on PATH. The full real-LLM `apply` flow through the packaged app is OPTIONAL here (covered by earlier acceptance runs).

- [ ] **Step 5: Commit + push**

```bash
git add scripts/build_app.sh scripts/build_app.ps1 app/THIRD_PARTY_NOTICES.md
git commit -m "build: pyinstaller packaging scripts with bundled portable blender"
git push
```

Note: `dist/` and `.build-app/` must be gitignored — add both to `.gitignore` in this commit if not already present.

---

## Self-Review Notes

- Spec coverage: §2 architecture (Task 5 + Task 1 data dir), §3 Blender bundling (Task 2 + 6), §4 BYOK (Task 3 + 4), §5 packaging (Task 6; steampipe/signing explicitly out per spec), §6 error handling (Task 2 error message, Task 4 key-guidance), §7 tests (each task), §9 acceptance (Task 6 step 4 on macOS; Windows acceptance deferred to the Windows machine, matching the spec's per-platform build decision).
- Spec deviation (documented): `app/paths.py` → `orchestrator/orchestrator/paths.py` (orchestrator must not depend on the app shell).
- Type consistency: `user_data_dir() -> Path`; `find_blender() -> str | None`; `SETTINGS_KEYS` mapping used identically in Task 3 and Task 4; `make_server(..., settings_path=None)` consistent between Tasks 4 and 5 (Task 5 relies on the default).
- CLI unchanged: default session/workdir paths untouched; new env vars only.
