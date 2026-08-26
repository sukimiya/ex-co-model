"""Pure functions that translate OpTree nodes into Blender bpy code strings.

Each emitted segment assumes the scene starts empty and ends containing only
the node's result object(s), written to `out` as GLB (or FBX for export).
"""

from optree.schema import (
    AttachPartParams,
    BevelParams,
    ExportFbxParams,
    PrimitiveParams,
    ScaleToParams,
)


def _fmt_num(x: float) -> str:
    """Render whole floats without a trailing .0 (pydantic coerces ints)."""
    return str(int(x)) if x == int(x) else str(x)


def _fmt_vec3(t: tuple[float, float, float]) -> str:
    return "(" + ", ".join(_fmt_num(v) for v in t) + ")"


def _import_glb(path: str) -> str:
    return (
        f"bpy.ops.import_scene.gltf(filepath={path!r})\n"
        "imported = [o for o in bpy.context.selected_objects if o.type == 'MESH']\n"
    )


def _export_glb(path: str) -> str:
    return f"bpy.ops.export_scene.gltf(filepath={path!r}, export_format='GLB')\n"


def emit_primitive(out: str, p: PrimitiveParams) -> str:
    if p.type == "box":
        code = (
            f"bpy.ops.mesh.primitive_cube_add(size=1, location={_fmt_vec3(tuple(p.location))})\n"
            "obj = bpy.context.active_object\n"
            f"obj.dimensions = {_fmt_vec3(tuple(p.size))}\n"
            "bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)\n"
        )
    else:
        code = (
            f"bpy.ops.mesh.primitive_cylinder_add(vertices={p.vertices}, "
            f"radius={p.radius}, depth={p.depth}, location={_fmt_vec3(tuple(p.location))})\n"
            "obj = bpy.context.active_object\n"
        )
    return code + _export_glb(out)


def emit_bevel(out: str, src: str, p: BevelParams) -> str:
    return (
        _import_glb(src)
        + "obj = imported[0]\n"
        + "mod = obj.modifiers.new(name='bevel', type='BEVEL')\n"
        + f"mod.width = {p.width}\n"
        + f"mod.segments = {p.segments}\n"
        + "bpy.context.view_layer.objects.active = obj\n"
        + "bpy.ops.object.modifier_apply(modifier='bevel')\n"
        + _export_glb(out)
    )


def emit_boolean_subtract(out: str, target: str, cutter: str) -> str:
    return (
        _import_glb(target)
        + "target_obj = imported[0]\n"
        + "bpy.ops.object.select_all(action='DESELECT')\n"
        + _import_glb(cutter)
        + "cutter_obj = imported[0]\n"
        + "mod = target_obj.modifiers.new(name='bool', type='BOOLEAN')\n"
        + "mod.operation = 'DIFFERENCE'\n"
        + "mod.solver = 'EXACT'\n"
        + "mod.object = cutter_obj\n"
        + "bpy.context.view_layer.objects.active = target_obj\n"
        + "bpy.ops.object.modifier_apply(modifier='bool')\n"
        + "bpy.data.objects.remove(cutter_obj)\n"
        + "bpy.ops.object.select_all(action='DESELECT')\n"
        + "target_obj.select_set(True)\n"
        + _export_glb(out)
    )


def emit_scale_to(out: str, src: str, p: ScaleToParams) -> str:
    return (
        _import_glb(src)
        + "from mathutils import Vector\n"
        + "mins = Vector((1e18, 1e18, 1e18))\n"
        + "maxs = Vector((-1e18, -1e18, -1e18))\n"
        + "for o in imported:\n"
        + "    for corner in o.bound_box:\n"
        + "        w = o.matrix_world @ Vector(corner)\n"
        + "        mins = Vector(map(min, mins, w))\n"
        + "        maxs = Vector(map(max, maxs, w))\n"
        + "dims = maxs - mins\n"
        + f"factor = {float(p.length_m)} / max(dims.x, dims.y, dims.z)\n"
        + "for o in imported:\n"
        + "    o.scale = tuple(s * factor for s in o.scale)\n"
        + "bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)\n"
        + _export_glb(out)
    )


def emit_export_fbx(out: str, src: str, p: ExportFbxParams) -> str:
    return (
        _import_glb(src)
        + f"bpy.ops.export_scene.fbx(filepath={out!r})\n"
    )


def emit_attach_part(out: str, parent: str, part_path: str, p: AttachPartParams) -> str:
    """Import parent + library part, place the part as a rigid body (meters/degrees,
    part origin in world frame), export combined scene."""
    return (
        _import_glb(parent)
        + "bpy.ops.object.select_all(action='DESELECT')\n"
        + _import_glb(part_path)
        + "import math\n"
        + "bpy.ops.object.empty_add(type='PLAIN_AXES')\n"
        + "rig = bpy.context.active_object\n"
        + "for o in imported:\n"
        + "    o.parent = rig\n"
        + f"rig.location = {_fmt_vec3(p.location)}\n"
        + f"rig.rotation_euler = tuple(math.radians(a) for a in {_fmt_vec3(p.rotation_deg)})\n"
        + f"rig.scale = ({_fmt_num(p.scale)},) * 3\n"
        + _export_glb(out)
    )
