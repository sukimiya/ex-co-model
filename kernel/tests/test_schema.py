import json

import pytest
from pydantic import ValidationError

from optree.schema import (
    ExportFbxParams,
    OpTree,
    PrimitiveParams,
    ScaleToParams,
    load_optree,
)


def valid_tree_dict() -> dict:
    return {
        "nodes": {
            "hull": {
                "op": "primitive",
                "params": {"type": "box", "size": [10, 3, 2]},
            },
            "hull_shaped": {
                "op": "bevel",
                "inputs": ["hull"],
                "params": {"width": 0.15, "segments": 3},
            },
            "out": {
                "op": "export_fbx",
                "inputs": ["hull_shaped"],
                "params": {"filename": "ship.fbx"},
            },
        }
    }


def test_valid_tree_parses():
    tree = OpTree.model_validate(valid_tree_dict())
    assert set(tree.nodes) == {"hull", "hull_shaped", "out"}
    assert tree.nodes["hull"].op == "primitive"
    assert tree.nodes["hull_shaped"].inputs == ["hull"]
    assert tree.nodes["hull_shaped"].params.width == 0.15


def test_unknown_input_ref_rejected():
    data = valid_tree_dict()
    data["nodes"]["hull_shaped"]["inputs"] = ["nonexistent"]
    with pytest.raises(ValidationError, match="unknown node"):
        OpTree.model_validate(data)


def test_unknown_op_rejected():
    data = valid_tree_dict()
    data["nodes"]["hull"]["op"] = "explode"
    with pytest.raises(ValidationError):
        OpTree.model_validate(data)


def test_scale_to_rejects_nonpositive_length():
    data = {
        "nodes": {
            "a": {"op": "primitive", "params": {"type": "box"}},
            "b": {"op": "scale_to", "inputs": ["a"], "params": {"length_m": 0}},
        }
    }
    with pytest.raises(ValidationError):
        OpTree.model_validate(data)


def test_load_optree_roundtrip(tmp_path):
    p = tmp_path / "tree.json"
    p.write_text(json.dumps(valid_tree_dict()), encoding="utf-8")
    tree = load_optree(p)
    assert tree.nodes["out"].params.filename == "ship.fbx"


def test_export_filename_rejects_parent_escape():
    with pytest.raises(ValidationError):
        ExportFbxParams(filename="../evil.fbx")


def test_export_filename_rejects_subdirectory():
    with pytest.raises(ValidationError):
        ExportFbxParams(filename="sub/dir.fbx")


def test_export_filename_requires_fbx_extension():
    with pytest.raises(ValidationError):
        ExportFbxParams(filename="model.glb")


def test_primitive_size_rejects_infinite():
    with pytest.raises(ValidationError):
        PrimitiveParams(type="box", size=[float("inf"), 1, 1])


def test_scale_to_rejects_nan_length():
    with pytest.raises(ValidationError):
        ScaleToParams(length_m=float("nan"))
