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
    if not blender_available():
        raise BlenderError("blender not found on PATH; install Blender >= 4.0")
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    script_path = workdir / "_session.py"
    script_path.write_text(script, encoding="utf-8")
    # blender exits 0 even when --python raises; wrap the session script in a
    # runner that exits non-zero on any exception so failures are detectable.
    runner_path = workdir / "_runner.py"
    runner = (
        "import runpy, sys, traceback\n"
        "try:\n"
        f"    runpy.run_path({str(script_path)!r})\n"
        "except SystemExit:\n"
        "    raise\n"
        "except BaseException:\n"
        "    traceback.print_exc()\n"
        "    sys.exit(1)\n"
    )
    runner_path.write_text(runner, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["blender", "-b", "--factory-startup", "--python", str(runner_path)],
            capture_output=True,
            text=True,
            cwd=workdir,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise BlenderError("blender timed out after 300s") from None
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-20:])
        raise BlenderError(f"blender exited {proc.returncode}:\n{tail}")
