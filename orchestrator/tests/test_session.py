import json

from orchestrator.llm import FakeLLMClient
from orchestrator.session import Session

VALID_TREE = {
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"], "params": {"filename": "ship.fbx"}},
    }
}


def test_new_session_has_no_tree(tmp_path):
    assert Session(tmp_path / "s.json").tree is None


def test_apply_persists_tree(tmp_path):
    path = tmp_path / "s.json"
    session = Session(path)
    llm = FakeLLMClient([json.dumps(VALID_TREE)])
    result = session.apply(llm, "一艘护卫舰")
    assert result.rounds == 1
    assert json.loads(path.read_text())["nodes"]["hull"]["op"] == "primitive"


def test_session_reloads_persisted_tree(tmp_path):
    path = tmp_path / "s.json"
    Session(path).apply(FakeLLMClient([json.dumps(VALID_TREE)]), "一艘护卫舰")
    reloaded = Session(path)
    assert reloaded.tree is not None
    assert set(reloaded.tree.nodes) == {"hull", "out"}


def test_second_apply_sees_existing_tree(tmp_path):
    path = tmp_path / "s.json"
    session = Session(path)
    session.apply(FakeLLMClient([json.dumps(VALID_TREE)]), "一艘护卫舰")
    llm = FakeLLMClient([json.dumps(VALID_TREE)])
    session.apply(llm, "加长到40米")
    assert '"hull"' in llm.calls[0][1]["content"]  # current tree embedded
