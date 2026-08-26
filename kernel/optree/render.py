"""Headless preview rendering: GLB in, framed PNG out."""

from pathlib import Path

from optree.blender_session import run_blender_script
from optree.errors import BlenderError

# bbox auto-framing; two area lights + gray world. energies scale with scene size.
_RENDER_TEMPLATE = '''
import bpy
from mathutils import Vector

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={glb!r})

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
mins = Vector((1e18, 1e18, 1e18))
maxs = Vector((-1e18, -1e18, -1e18))
for o in meshes:
    for corner in o.bound_box:
        w = o.matrix_world @ Vector(corner)
        mins = Vector(map(min, mins, w))
        maxs = Vector(map(max, maxs, w))
center = (mins + maxs) / 2
dims = maxs - mins
radius = max(max(dims.x, dims.y, dims.z) / 2, 0.5)

mat = bpy.data.materials.new("preview")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.72, 0.75, 0.8, 1)
bsdf.inputs["Roughness"].default_value = 0.55
for o in meshes:
    if not o.data.materials:
        o.data.materials.append(mat)

dist = radius * 4.0

def area_light(offset, energy):
    bpy.ops.object.light_add(type="AREA", location=center + offset)
    lamp = bpy.context.active_object
    lamp.data.energy = energy
    lamp.data.size = radius * 2
    lamp.rotation_euler = (center - lamp.location).to_track_quat("-Z", "Y").to_euler()

area_light(Vector((dist * 0.7, -dist * 0.7, dist * 0.7)), radius * radius * 60)
area_light(Vector((-dist * 0.7, dist * 0.7, -dist * 0.2)), radius * radius * 25)

bpy.ops.object.camera_add(location=center + Vector((dist * 0.75, -dist * 0.75, dist * 0.5)))
cam = bpy.context.active_object
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.35, 0.4, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.5
bpy.context.scene.world = world

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = {size}
scene.render.resolution_y = {size} * 9 // 16
scene.render.filepath = {out!r}
bpy.ops.render.render(write_still=True)
'''


def render_glb(glb: str | Path, out_png: str | Path, workdir: Path,
               size: int = 1024) -> Path:
    """Render a framed preview of a glb to png. Raises BlenderError on failure."""
    out = Path(out_png).resolve()
    script = _RENDER_TEMPLATE.format(glb=str(Path(glb).resolve()), out=str(out), size=size)
    run_blender_script(script, Path(workdir))
    if not out.exists():
        raise BlenderError(f"render produced no output: {out}")
    return out
