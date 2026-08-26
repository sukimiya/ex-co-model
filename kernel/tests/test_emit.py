from optree.emit import (
    emit_bevel,
    emit_boolean_subtract,
    emit_export_fbx,
    emit_primitive,
    emit_scale_to,
)
from optree.schema import BevelParams, ExportFbxParams, PrimitiveParams, ScaleToParams


def test_emit_box_primitive():
    code = emit_primitive("/tmp/a.glb", PrimitiveParams(type="box", size=(10, 3, 2)))
    assert "primitive_cube_add" in code
    assert "(10, 3, 2)" in code
    assert "export_scene.gltf" in code
    assert "/tmp/a.glb" in code


def test_emit_cylinder_primitive():
    code = emit_primitive("/tmp/c.glb", PrimitiveParams(type="cylinder", radius=1.5, depth=6))
    assert "primitive_cylinder_add" in code
    assert "radius=1.5" in code
    assert "depth=6" in code


def test_emit_bevel_applies_modifier():
    code = emit_bevel("/tmp/b.glb", "/tmp/a.glb", BevelParams(width=0.15, segments=3))
    assert "import_scene.gltf" in code
    assert "/tmp/a.glb" in code
    assert "type='BEVEL'" in code
    assert "mod.width = 0.15" in code
    assert "modifier_apply" in code


def test_emit_boolean_subtract_removes_cutter():
    code = emit_boolean_subtract("/tmp/out.glb", "/tmp/t.glb", "/tmp/c.glb")
    assert code.index("/tmp/t.glb") < code.index("/tmp/c.glb")  # target imported first
    assert "operation = 'DIFFERENCE'" in code
    assert "solver = 'EXACT'" in code
    assert "bpy.data.objects.remove(cutter_obj)" in code


def test_emit_scale_to_computes_uniform_factor():
    code = emit_scale_to("/tmp/s.glb", "/tmp/a.glb", ScaleToParams(length_m=28))
    assert "28.0 / max(" in code
    assert "transform_apply" in code
    assert "/tmp/s.glb" in code


def test_emit_export_fbx():
    code = emit_export_fbx("/tmp/out/ship.fbx", "/tmp/s.glb", ExportFbxParams(filename="ship.fbx"))
    assert "export_scene.fbx" in code
    assert "/tmp/out/ship.fbx" in code
