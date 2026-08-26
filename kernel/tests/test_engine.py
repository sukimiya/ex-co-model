import json

import pytest

from optree.engine import build
from optree.errors import OpTreeError
from optree.parts import PartsIndex
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


def attach_tree() -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "armed": {
                "op": "attach_part",
                "inputs": ["hull"],
                "params": {"part": "pdc_turret", "location": [0, 0, 2]},
            },
            "out": {
                "op": "export_fbx",
                "inputs": ["armed"],
                "params": {"filename": "armed.fbx"},
            },
        }
    })


@pytest.fixture
def mini_parts(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "turret.glb").write_bytes(b"fake-glb")
    (parts / "index.json").write_text(json.dumps({
        "parts": {"pdc_turret": {"file": "turret.glb", "description": "t"}}
    }), encoding="utf-8")
    return parts


def test_attach_part_requires_parts_dir(tmp_path):
    with pytest.raises(OpTreeError, match="parts_dir"):
        build(attach_tree(), tmp_path / "w")


def test_attach_part_injects_part_hash_into_key(tmp_path, mini_parts):
    """part file content changes -> node key changes -> cache invalidates."""
    from optree.keys import node_key
    tree = attach_tree()
    node = tree.nodes["armed"]
    idx1 = PartsIndex.load(mini_parts)
    node.params.part_hash = idx1.content_hash("pdc_turret")
    k1 = node_key(node, ["hullkey"])
    (mini_parts / "turret.glb").write_bytes(b"fake-glb-v2")
    node.params.part_hash = idx1.content_hash("pdc_turret")
    assert node_key(node, ["hullkey"]) != k1


def rotated_attach_tree() -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "armed": {
                "op": "attach_part",
                "inputs": ["hull"],
                "params": {"part": "engine_nozzle", "rotation_deg": [180, 0, 0]},
            },
            "out": {
                "op": "export_fbx",
                "inputs": ["armed"],
                "params": {"filename": "armed.fbx"},
            },
        }
    })


@requires_blender
def test_attach_part_rotation_is_rigid_body(tmp_path):
    """A 180° rotation must flip the whole part, sub-objects included.

    engine_nozzle's throat cylinder sits at world z ≈ +1.35 unrotated; after a
    rigid 180° flip it must be at z ≈ -1.35. With per-mesh (non-rigid)
    transforms every mesh rotates about its own origin and no origin moves.
    """
    import subprocess
    repo_parts = __import__("pathlib").Path(__file__).parent.parent.parent / "parts"
    result = build(rotated_attach_tree(), tmp_path / "w", parts_dir=repo_parts)
    probe = tmp_path / "probe.py"
    zs_file = tmp_path / "zs.txt"
    probe.write_text(
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        f"bpy.ops.import_scene.gltf(filepath={str(result.glbs['armed'])!r})\n"
        "zs = [o.matrix_world.translation.z\n"
        "      for o in bpy.context.scene.objects if o.type == 'MESH']\n"
        f"open({str(zs_file)!r}, 'w').write('\\n'.join(str(z) for z in zs))\n"
    )
    subprocess.run(
        ["blender", "-b", "--factory-startup", "--python", str(probe)],
        check=True, capture_output=True,
    )
    zs = [float(line) for line in zs_file.read_text().splitlines()]
    assert min(zs) < -1.0  # throat cylinder flipped below the part origin


@requires_blender
def test_build_with_real_library(tmp_path):
    """End-to-end: attach a real library part, export fbx containing 2+ objects."""
    import subprocess
    repo_parts = __import__("pathlib").Path(__file__).parent.parent.parent / "parts"
    result = build(attach_tree(), tmp_path / "w", parts_dir=repo_parts)
    assert result.exports[0].exists()
    # count meshes inside the attached-node glb via blender
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        f"bpy.ops.import_scene.gltf(filepath={str(result.glbs['armed'])!r})\n"
        "n = len([o for o in bpy.context.scene.objects if o.type == 'MESH'])\n"
        f"open({str(tmp_path / 'count.txt')!r}, 'w').write(str(n))\n"
    )
    subprocess.run(
        ["blender", "-b", "--factory-startup", "--python", str(probe)],
        check=True, capture_output=True,
    )
    assert int((tmp_path / "count.txt").read_text()) >= 2
