from dataclasses import dataclass, field
from pathlib import Path

from optree import emit
from optree.blender_session import run_blender_script
from optree.errors import OpTreeError
from optree.graph import topo_order
from optree.keys import node_key
from optree.parts import PartsIndex
from optree.schema import OpTree

_SCENE_RESET = "bpy.ops.object.select_all(action='SELECT')\nbpy.ops.object.delete()\n"


@dataclass
class BuildResult:
    glbs: dict[str, Path] = field(default_factory=dict)
    exports: list[Path] = field(default_factory=list)


def build(tree: OpTree, workdir: Path, parts_dir: Path | None = None) -> BuildResult:
    """Execute an OpTree. Cached nodes are skipped; dirty nodes run in one
    headless Blender session. Returns paths to cached glbs and exported fbx."""
    workdir = Path(workdir).resolve()
    index = None
    if any(n.op == "attach_part" for n in tree.nodes.values()):
        if parts_dir is None:
            raise OpTreeError("tree uses attach_part; pass parts_dir")
        index = PartsIndex.load(parts_dir)
    cache = workdir / "cache"
    outdir = workdir / "out"
    cache.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    order = topo_order(tree)
    keys: dict[str, str] = {}
    glbs: dict[str, Path] = {}
    exports: dict[str, Path] = {}
    dirty: list[str] = []

    for name in order:
        node = tree.nodes[name]
        if node.op == "attach_part":
            node.params.part_hash = index.content_hash(node.params.part)
        key = node_key(node, [keys[i] for i in node.inputs])
        keys[name] = key
        if node.op == "export_fbx":
            exports[name] = outdir / node.params.filename
            dirty.append(name)  # re-export every build; cheap relative to geometry
        else:
            glbs[name] = cache / f"{key}.glb"
            if not glbs[name].exists():
                dirty.append(name)

    if dirty:
        script = "import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
        for name in dirty:
            node = tree.nodes[name]
            if node.op == "primitive":
                script += emit.emit_primitive(str(glbs[name]), node.params)
            elif node.op == "bevel":
                script += emit.emit_bevel(str(glbs[name]), str(glbs[node.inputs[0]]), node.params)
            elif node.op == "boolean_subtract":
                script += emit.emit_boolean_subtract(
                    str(glbs[name]), str(glbs[node.inputs[0]]), str(glbs[node.inputs[1]])
                )
            elif node.op == "scale_to":
                script += emit.emit_scale_to(str(glbs[name]), str(glbs[node.inputs[0]]), node.params)
            elif node.op == "attach_part":
                script += emit.emit_attach_part(
                    str(glbs[name]), str(glbs[node.inputs[0]]),
                    str(index.resolve(node.params.part)), node.params, name,
                )
            elif node.op == "set_material":
                script += emit.emit_set_material(str(glbs[name]), str(glbs[node.inputs[0]]), node.params)
            elif node.op == "export_fbx":
                script += emit.emit_export_fbx(str(exports[name]), str(glbs[node.inputs[0]]), node.params)
            script += _SCENE_RESET
        run_blender_script(script, workdir)

    return BuildResult(glbs=glbs, exports=list(exports.values()))
