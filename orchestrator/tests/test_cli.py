import json

import pytest

from optree.schema import OpTree

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
    assert "round 1" in out or "rounds=1" in out
    assert session.exists()


def test_apply_llm_failure_exit_1(tmp_path, capsys):
    fake = FakeLLMClient(["garbage"] * 3)
    assert main(["apply", "x", "--session", str(tmp_path / "s.json")], llm=fake) == 1
    assert "error" in capsys.readouterr().err


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
