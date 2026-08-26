import shutil
import subprocess
from pathlib import Path

from optree.errors import BlenderError


def blender_available() -> bool:
    return shutil.which("blender") is not None


def run_blender_script(script: str, workdir: Path) -> None:
    """Run a python script in one headless Blender process.

    Raises BlenderError with the tail of blender's output on failure.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    script_path = workdir / "_session.py"
    script_path.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        ["blender", "-b", "--factory-startup", "--python", str(script_path)],
        capture_output=True,
        text=True,
        cwd=workdir,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-20:])
        raise BlenderError(f"blender exited {proc.returncode}:\n{tail}")
