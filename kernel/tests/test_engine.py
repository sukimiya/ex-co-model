from optree.engine import build
from optree.schema import OpTree
from tests.conftest import requires_blender


def ship_tree(bevel_width: float = 0.15) -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "hull": {
                "op": "primitive",
                "params": {"type": "box", "size": [10, 3, 2]},
            },
            "cutter": {
                "op": "primitive",
                "params": {"type": "box", "size": [2, 1, 0.8], "location": [0, 0, 1]},
            },
            "slotted": {
                "op": "boolean_subtract",
                "inputs": ["hull", "cutter"],
            },
            "shaped": {
                "op": "bevel",
                "inputs": ["slotted"],
                "params": {"width": bevel_width, "segments": 2},
            },
            "scaled": {
                "op": "scale_to",
                "inputs": ["shaped"],
                "params": {"length_m": 28},
            },
            "out": {
                "op": "export_fbx",
                "inputs": ["scaled"],
                "params": {"filename": "ship.fbx"},
            },
        }
    })


@requires_blender
def test_build_produces_fbx_and_cached_glbs(tmp_path):
    result = build(ship_tree(), tmp_path)
    assert result.exports == [tmp_path / "out" / "ship.fbx"]
    assert result.exports[0].exists() and result.exports[0].stat().st_size > 0
    # every geometry node has a cached glb
    assert len(result.glbs) == 5
    for p in result.glbs.values():
        assert p.exists()


@requires_blender
def test_rebuild_is_incremental(tmp_path):
    build(ship_tree(), tmp_path)
    mtimes_before = {k: p.stat().st_mtime_ns for k, p in build(ship_tree(), tmp_path).glbs.items()}

    # unchanged tree: nothing recomputed
    result2 = build(ship_tree(), tmp_path)
    for k, p in result2.glbs.items():
        assert p.stat().st_mtime_ns == mtimes_before[k]

    # change bevel width: hull/cutter/slotted cached (upstream of bevel),
    # shaped + scaled get new cache keys (downstream)
    mtimes_cached = {k: p.stat().st_mtime_ns for k, p in result2.glbs.items()}
    result3 = build(ship_tree(bevel_width=0.3), tmp_path)
    assert result3.glbs["hull"].stat().st_mtime_ns == mtimes_cached["hull"]
    assert result3.glbs["cutter"].stat().st_mtime_ns == mtimes_cached["cutter"]
    assert result3.glbs["slotted"].stat().st_mtime_ns == mtimes_cached["slotted"]
    assert result3.glbs["shaped"] != result2.glbs["shaped"]  # new cache key
    assert result3.glbs["shaped"].exists()
    assert result3.glbs["scaled"] != result2.glbs["scaled"]  # downstream also recomputed
