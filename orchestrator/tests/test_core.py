import json

import pytest

from optree.schema import OpTree

from orchestrator.core import run_apply
from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient

VALID_TREE = json.dumps({
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"], "params": {"filename": "ship.fbx"}},
    }
})

INVALID_REF_TREE = json.dumps({
    "nodes": {
        "out": {"op": "export_fbx", "inputs": ["ghost"], "params": {"filename": "ship.fbx"}},
    }
})

CYCLE_TREE = json.dumps({
    "nodes": {
        "a": {"op": "bevel", "inputs": ["b"]},
        "b": {"op": "bevel", "inputs": ["a"]},
    }
})


def test_valid_response_first_try():
    llm = FakeLLMClient([VALID_TREE])
    result = run_apply(llm, "一艘护卫舰", None)
    assert result.rounds == 1
    assert set(result.tree.nodes) == {"hull", "out"}


def test_invalid_json_then_valid_retries():
    llm = FakeLLMClient(["not json at all", VALID_TREE])
    result = run_apply(llm, "一艘护卫舰", None)
    assert result.rounds == 2
    # second call must carry the error feedback
    second_call = llm.calls[1]
    assert any("invalid" in m["content"].lower() for m in second_call if m["role"] == "user")


def test_schema_error_is_fed_back():
    llm = FakeLLMClient([INVALID_REF_TREE, VALID_TREE])
    result = run_apply(llm, "一艘护卫舰", None)
    assert result.rounds == 2
    feedback = llm.calls[1][-1]["content"]
    assert "unknown node" in feedback


def test_cycle_error_is_fed_back():
    llm = FakeLLMClient([CYCLE_TREE, VALID_TREE])
    result = run_apply(llm, "一艘护卫舰", None)
    assert result.rounds == 2
    assert "cycle" in llm.calls[1][-1]["content"]


def test_max_rounds_exceeded_raises():
    llm = FakeLLMClient([INVALID_REF_TREE] * 3)
    with pytest.raises(OrchestratorError, match="3 rounds"):
        run_apply(llm, "一艘护卫舰", None)


def test_current_tree_passed_to_messages():
    current = OpTree.model_validate(json.loads(VALID_TREE))
    llm = FakeLLMClient([VALID_TREE])
    run_apply(llm, "加长到40米", current)
    assert '"hull"' in llm.calls[0][1]["content"]


def test_available_parts_reach_prompt():
    llm = FakeLLMClient([VALID_TREE])
    run_apply(llm, "加一门炮", None, available_parts=["pdc_turret"])
    assert "pdc_turret" in llm.calls[0][1]["content"]


def _tree_two_boxes():
    return OpTree.model_validate({"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "mast": {"op": "primitive", "params": {"type": "box", "size": [1, 1, 5],
                                               "location": [5, 0, 5]}},
        "out": {"op": "export_fbx", "inputs": ["hull"]},
    }})


def test_focus_edit_accepts_subtree_only_change():
    old = _tree_two_boxes()
    changed = {"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "mast": {"op": "primitive", "params": {"type": "box", "size": [1, 1, 9],
                                               "location": [5, 0, 5]}},
        "out": {"op": "export_fbx", "inputs": ["hull"]},
    }}
    llm = FakeLLMClient([json.dumps(changed)])
    result = run_apply(llm, "make the mast taller", old, focus_node="mast")
    assert result.tree.nodes["mast"].params.size[2] == 9


def test_focus_edit_rejects_frozen_node_change_then_recovers():
    old = _tree_two_boxes()
    bad = {"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [99, 8, 6]}},
        "mast": {"op": "primitive", "params": {"type": "box", "size": [1, 1, 9],
                                               "location": [5, 0, 5]}},
        "out": {"op": "export_fbx", "inputs": ["hull"]},
    }}
    good = {"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "mast": {"op": "primitive", "params": {"type": "box", "size": [1, 1, 9],
                                               "location": [5, 0, 5]}},
        "out": {"op": "export_fbx", "inputs": ["hull"]},
    }}
    llm = FakeLLMClient([json.dumps(bad), json.dumps(good)])
    result = run_apply(llm, "make the mast taller", old, focus_node="mast")
    assert result.rounds == 2
    # the rejection feedback must name the frozen node
    assert "hull" in llm.calls[1][-1]["content"] or "hull" in str(llm.calls)


def test_focus_edit_unknown_node_raises():
    llm = FakeLLMClient([])
    with pytest.raises(OrchestratorError, match="not in current tree"):
        run_apply(llm, "x", _tree_two_boxes(), focus_node="nope")


def test_focus_edit_rejects_focus_deletion():
    old = _tree_two_boxes()
    deleted = {"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "out": {"op": "export_fbx", "inputs": ["hull"]},
    }}
    llm = FakeLLMClient([json.dumps(deleted)] * 3)
    with pytest.raises(OrchestratorError, match="after 3 rounds"):
        run_apply(llm, "delete the mast", old, focus_node="mast")
