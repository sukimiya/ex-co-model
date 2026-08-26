import pytest

from optree.blender_session import run_blender_script
from optree.errors import BlenderError
from tests.conftest import requires_blender


@requires_blender
def test_run_script_creates_file(tmp_path):
    out = tmp_path / "hello.glb"
    script = (
        "import bpy\n"
        "bpy.ops.mesh.primitive_cube_add(size=2)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(out)!r}, export_format='GLB')\n"
    )
    run_blender_script(script, tmp_path)
    assert out.exists() and out.stat().st_size > 0


@requires_blender
def test_bad_script_raises_blender_error(tmp_path):
    with pytest.raises(BlenderError, match="blender exited"):
        run_blender_script("import bpy\nbpy.ops.nonexistent.call()\n", tmp_path)
