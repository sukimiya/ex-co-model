import shutil
import subprocess
from pathlib import Path

from optree.parts import PartsIndex
from tests.conftest import requires_blender

PARTS_DIR = Path(__file__).parent.parent.parent / "parts"


@requires_blender
def test_build_parts_regenerates_glbs(tmp_path):
    """The generator script must produce all 3 glbs into a copied parts dir."""
    work = tmp_path / "parts"
    work.mkdir()
    shutil.copy(PARTS_DIR / "index.json", work / "index.json")
    script = PARTS_DIR / "build_parts.py"
    subprocess.run(
        ["blender", "-b", "--factory-startup", "--python", str(script), "--", str(work)],
        check=True, capture_output=True,
    )
    idx = PartsIndex.load(work)
    assert sorted(idx.names()) == ["comm_antenna", "engine_nozzle", "pdc_turret"]
    for name in idx.names():
        assert idx.resolve(name).stat().st_size > 500  # real geometry, not empty
