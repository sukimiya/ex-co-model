from optree.engine import build
from optree.render import render_glb
from optree.schema import OpTree
from tests.conftest import requires_blender


@requires_blender
def test_render_glb_produces_nontrivial_png(tmp_path):
    tree = OpTree.model_validate({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "out": {"op": "export_fbx", "inputs": ["hull"],
                    "params": {"filename": "hull.fbx"}},
        }
    })
    result = build(tree, tmp_path / "b")
    png = render_glb(result.glbs["hull"], tmp_path / "preview.png", tmp_path / "r")
    assert png.exists()
    # a uniformly-black or empty render compresses to a few KB; real geometry > 20KB
    assert png.stat().st_size > 20_000
