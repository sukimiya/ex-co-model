import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import optree.blender_session
from optree.blender_session import find_blender, run_blender_script
from optree.errors import BlenderError
from tests.conftest import requires_blender


@requires_blender
def test_run_script_creates_file(tmp_path):
    out = tmp_path / "hello.glb"
    script = (
        "import bpy\n"
        "bpy.ops.mesh.primitive_cube_add(size=2)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(out)!r}, export_format='GLB')\n"
    )
    run_blender_script(script, tmp_path)
    assert out.exists() and out.stat().st_size > 0


@requires_blender
def test_bad_script_raises_blender_error(tmp_path):
    with pytest.raises(BlenderError, match="blender exited"):
        run_blender_script("import bpy\nbpy.ops.nonexistent.call()\n", tmp_path)


def test_missing_blender_raises_blender_error(monkeypatch, tmp_path):
    monkeypatch.setattr(optree.blender_session, "find_blender", lambda: None)
    with pytest.raises(BlenderError, match="blender not found"):
        run_blender_script("pass", tmp_path)


def test_blender_timeout_raises_blender_error(monkeypatch, tmp_path):
    monkeypatch.setattr(optree.blender_session, "find_blender", lambda: "blender")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="blender", timeout=300)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BlenderError, match="timed out"):
        run_blender_script("pass", tmp_path)


def test_workdir_resolved_to_absolute(monkeypatch, tmp_path):
    monkeypatch.setattr(optree.blender_session, "find_blender", lambda: "blender")
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_blender_script("pass", Path("relative-dir"))
    script_arg = captured["cmd"][captured["cmd"].index("--python") + 1]
    assert Path(script_arg).is_absolute()
    assert Path(script_arg).parent == Path(captured["cwd"]) == tmp_path / "relative-dir"


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
