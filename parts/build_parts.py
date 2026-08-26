"""Regenerate the sample library parts. Run:
blender -b --factory-startup --python parts/build_parts.py -- <output_dir>
"""
import math
import sys
from pathlib import Path

import bpy

OUT_DIR = Path(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else Path("parts")


def clean():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def cyl(radius, depth, loc=(0, 0, 0), rot_deg=(0, 0, 0), vertices=24):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    obj = bpy.context.active_object
    obj.rotation_euler = tuple(math.radians(a) for a in rot_deg)
    return obj


def cone(r1, r2, depth, loc=(0, 0, 0), vertices=24):
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=r1, radius2=r2,
                                    depth=depth, location=loc)
    return bpy.context.active_object


def box(size, loc=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.active_object
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def export(name):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(OUT_DIR / f"{name}.glb"), export_format="GLB")


def build_pdc_turret():
    cyl(0.6, 0.3, loc=(0, 0, 0.15))                     # base ring
    box((0.9, 0.5, 0.5), loc=(0, 0, 0.55))              # housing
    cyl(0.06, 0.9, loc=(0, -0.12, 1.15), rot_deg=(90, 0, 0))  # barrel L
    cyl(0.06, 0.9, loc=(0, 0.12, 1.15), rot_deg=(90, 0, 0))   # barrel R
    export("pdc_turret")


def build_engine_nozzle():
    cone(1.0, 0.45, 2.5)                                 # bell
    cyl(0.45, 0.3, loc=(0, 0, 1.35))                     # throat mount
    export("engine_nozzle")


def build_comm_antenna():
    cyl(0.05, 2.6, loc=(0, 0, 1.3))                      # mast
    cone(0.5, 0.05, 0.4, loc=(0, 0, 2.8))                # dish
    export("comm_antenna")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for builder in (build_pdc_turret, build_engine_nozzle, build_comm_antenna):
        clean()
        builder()


main()
