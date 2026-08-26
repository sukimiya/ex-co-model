import subprocess
from pathlib import Path

import pytest

import optree.blender_session
from optree.blender_session import run_blender_script
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
    monkeypatch.setattr(optree.blender_session, "blender_available", lambda: False)
    with pytest.raises(BlenderError, match="not found on PATH"):
        run_blender_script("pass", tmp_path)


def test_blender_timeout_raises_blender_error(monkeypatch, tmp_path):
    monkeypatch.setattr(optree.blender_session, "blender_available", lambda: True)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="blender", timeout=300)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BlenderError, match="timed out"):
        run_blender_script("pass", tmp_path)


def test_workdir_resolved_to_absolute(monkeypatch, tmp_path):
    monkeypatch.setattr(optree.blender_session, "blender_available", lambda: True)
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
