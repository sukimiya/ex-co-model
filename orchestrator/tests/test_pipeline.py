import json

import pytest

from optree.schema import OpTree

from orchestrator.errors import OrchestratorError
from orchestrator.pipeline import build_and_render, final_glb
from orchestrator.session import Session
from tests.conftest import requires_blender

TREE = {
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "shaped": {"op": "bevel", "inputs": ["hull"], "params": {"width": 0.3}},
        "out": {"op": "export_fbx", "inputs": ["shaped"],
                "params": {"filename": "ship.fbx"}},
    }
}


def test_final_glb_prefers_export_input(tmp_path):
    tree = OpTree.model_validate(TREE)
    from optree.engine import BuildResult
    fake = BuildResult(glbs={"hull": tmp_path / "a.glb", "shaped": tmp_path / "b.glb"})
    assert final_glb(tree, fake) == tmp_path / "b.glb"


def test_build_and_render_without_tree_raises(tmp_path):
    with pytest.raises(OrchestratorError, match="no session tree"):
        build_and_render(Session(tmp_path / "nope.json"), tmp_path / "w", None)


@requires_blender
def test_build_and_render_produces_png(tmp_path):
    session_path = tmp_path / "s.json"
    session_path.write_text(json.dumps(TREE), encoding="utf-8")
    png = build_and_render(Session(session_path), tmp_path / "w", None)
    assert png.exists() and png.stat().st_size > 20_000
