import shutil

import pytest

requires_blender = pytest.mark.skipif(
    shutil.which("blender") is None, reason="blender not on PATH"
)
