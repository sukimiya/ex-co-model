import json

from orchestrator.cli import main
from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient
from tests.conftest import requires_blender

VALID_TREE = json.dumps({
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"], "params": {"filename": "ship.fbx"}},
    }
})


def test_apply_creates_session(tmp_path, capsys):
    session = tmp_path / "s.json"
    fake = FakeLLMClient([VALID_TREE])
    assert main(["apply", "一艘护卫舰", "--session", str(session)], llm=fake) == 0
    out = capsys.readouterr().out
    assert "rounds=1" in out
    assert session.exists()


def test_apply_llm_failure_exit_1(tmp_path, capsys):
    fake = FakeLLMClient(["garbage"] * 3)
    assert main(["apply", "x", "--session", str(tmp_path / "s.json")], llm=fake) == 1
    assert "error" in capsys.readouterr().err


def test_apply_sdk_failure_presented_as_error(tmp_path, capsys):
    class FailingLLM:
        def complete(self, messages):
            raise OrchestratorError("llm request failed: boom")

    assert main(["apply", "x", "--session", str(tmp_path / "s.json")],
                llm=FailingLLM()) == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "llm request failed" in err


def test_show_corrupt_session_exit_1(tmp_path, capsys):
    session = tmp_path / "s.json"
    session.write_text('{"nodes": ', encoding="utf-8")
    assert main(["show", "--session", str(session)]) == 1
    assert "error:" in capsys.readouterr().err


def test_show_without_session_exit_1(tmp_path, capsys):
    assert main(["show", "--session", str(tmp_path / "nope.json")]) == 1


def test_show_prints_tree(tmp_path, capsys):
    session = tmp_path / "s.json"
    session.write_text(VALID_TREE, encoding="utf-8")
    assert main(["show", "--session", str(session)]) == 0
    assert '"hull"' in capsys.readouterr().out


@requires_blender
def test_build_produces_fbx(tmp_path, capsys):
    session = tmp_path / "s.json"
    session.write_text(VALID_TREE, encoding="utf-8")
    assert main(["build", "--session", str(session),
                 "--workdir", str(tmp_path / "build")]) == 0
    assert "ship.fbx" in capsys.readouterr().out
    assert (tmp_path / "build" / "out" / "ship.fbx").exists()


@requires_blender
def test_build_passes_parts_dir(tmp_path):
    """build with attach_part tree and --parts pointing at the repo library."""
    session = tmp_path / "s.json"
    session.write_text(json.dumps({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "armed": {
                "op": "attach_part",
                "inputs": ["hull"],
                "params": {"part": "pdc_turret", "location": [0, 0, 2]},
            },
            "out": {"op": "export_fbx", "inputs": ["armed"],
                    "params": {"filename": "armed.fbx"}},
        }
    }), encoding="utf-8")
    repo_parts = __import__("pathlib").Path(__file__).parent.parent.parent / "parts"
    assert main(["build", "--session", str(session),
                 "--workdir", str(tmp_path / "b"), "--parts", str(repo_parts)]) == 0
    assert (tmp_path / "b" / "out" / "armed.fbx").exists()


@requires_blender
def test_build_with_relative_parts_dir(tmp_path, monkeypatch):
    """Default --parts is the relative path ./parts; it must still work even
    though Blender subprocesses run with cwd=workdir."""
    session = tmp_path / "s.json"
    session.write_text(json.dumps({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "armed": {
                "op": "attach_part",
                "inputs": ["hull"],
                "params": {"part": "pdc_turret", "location": [0, 0, 2]},
            },
            "out": {"op": "export_fbx", "inputs": ["armed"],
                    "params": {"filename": "armed.fbx"}},
        }
    }), encoding="utf-8")
    repo_root = __import__("pathlib").Path(__file__).parent.parent.parent
    monkeypatch.chdir(repo_root)
    assert main(["build", "--session", str(session),
                 "--workdir", str(tmp_path / "b")]) == 0
    assert (tmp_path / "b" / "out" / "armed.fbx").exists()
