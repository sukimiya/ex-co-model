import pytest

from optree.schema import OpTree

from orchestrator.edit import add_part, cut_slot, remove_node, update_transform
from orchestrator.errors import OrchestratorError


def make_tree():
    return OpTree.model_validate({"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "gun": {"op": "attach_part", "inputs": ["hull"],
                "params": {"part": "pdc_turret", "location": [5, 0, 3]}},
        "out": {"op": "export_fbx", "inputs": ["gun"]},
    }})


def test_add_part():
    t = add_part(make_tree(), "ant", "comm_antenna", "hull", [0, 0, 3], [0, 0, 0], 1.0)
    assert t.nodes["ant"].op == "attach_part"
    assert t.nodes["ant"].inputs == ["hull"]
    assert t.nodes["ant"].params.part == "comm_antenna"


def test_add_part_unknown_parent_rejected():
    with pytest.raises(OrchestratorError):
        add_part(make_tree(), "x", "comm_antenna", "nope", [0, 0, 0], [0, 0, 0], 1.0)


def test_add_part_rewires_export_pointing_at_parent():
    t = add_part(make_tree(), "gun2", "pdc_turret", "gun", [5, 0, 6], [0, 0, 0], 1.0)
    assert t.nodes["out"].inputs == ["gun2"]


def test_add_part_leaves_export_on_other_branch_alone():
    t = add_part(make_tree(), "ant", "comm_antenna", "hull", [0, 0, 3], [0, 0, 0], 1.0)
    assert t.nodes["out"].inputs == ["gun"]  # export never pointed at "hull"


def test_add_part_without_export_unchanged():
    tree = OpTree.model_validate({"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
    }})
    t = add_part(tree, "ant", "comm_antenna", "hull", [0, 0, 3], [0, 0, 0], 1.0)
    assert set(t.nodes) == {"hull", "ant"}


def test_update_transform():
    t = update_transform(make_tree(), "gun", location=[9, 1, 3])
    assert tuple(t.nodes["gun"].params.location) == (9, 1, 3)
    assert t.nodes["gun"].params.scale == 1.0  # untouched


def test_update_transform_rejects_non_part():
    with pytest.raises(OrchestratorError):
        update_transform(make_tree(), "hull", location=[0, 0, 0])


def test_remove_node_rewires_child():
    t = remove_node(make_tree(), "gun")
    assert "gun" not in t.nodes
    assert t.nodes["out"].inputs == ["hull"]


def test_remove_node_still_referenced_no_input_rejected():
    with pytest.raises(OrchestratorError, match="still referenced"):
        remove_node(make_tree(), "hull")


def test_remove_leaf_errors_on_unknown():
    with pytest.raises(OrchestratorError):
        remove_node(make_tree(), "ghost")


def test_cut_slot():
    t = cut_slot(make_tree(), "slot1", "hull", [4, 2, 2], [10, 0, 3])
    assert t.nodes["slot1_cutter"].op == "primitive"
    assert t.nodes["slot1"].op == "boolean_subtract"
    assert t.nodes["slot1"].inputs == ["hull", "slot1_cutter"]


def test_cut_slot_duplicate_name_rejected():
    with pytest.raises(OrchestratorError):
        cut_slot(make_tree(), "hull", "hull", [1, 1, 1], [0, 0, 0])


def test_cut_slot_rewires_export_pointing_at_target():
    t = cut_slot(make_tree(), "slot1", "gun", [4, 2, 2], [10, 0, 3])
    assert t.nodes["out"].inputs == ["slot1"]


def test_cut_slot_leaves_export_on_other_branch_alone():
    t = cut_slot(make_tree(), "slot1", "hull", [4, 2, 2], [10, 0, 3])
    assert t.nodes["out"].inputs == ["gun"]  # export never pointed at "hull"


def test_cut_slot_without_export_unchanged():
    tree = OpTree.model_validate({"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
    }})
    t = cut_slot(tree, "slot1", "hull", [4, 2, 2], [10, 0, 3])
    assert set(t.nodes) == {"hull", "slot1_cutter", "slot1"}
