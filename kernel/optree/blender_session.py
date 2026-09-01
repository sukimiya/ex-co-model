import os
import shutil
import subprocess
import sys
from pathlib import Path

from optree.errors import BlenderError


def _bundled_blender() -> Path | None:
    """Blender shipped inside a PyInstaller bundle, next to the executable."""
    if not getattr(sys, "frozen", False):
        return None
    root = Path(sys.executable).resolve().parent
    candidates = [
        root / "blender" / "blender.exe",                                  # windows
        root / "blender" / "blender",                                      # linux
        root / "blender" / "Blender.app" / "Contents" / "MacOS" / "Blender",  # mac onedir
        root.parent / "Resources" / "blender" / "Blender.app" / "Contents" / "MacOS" / "Blender",  # mac .app
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_blender() -> str | None:
    """Lookup order: EXCO_BLENDER env -> bundled (PyInstaller) -> PATH."""
    override = os.environ.get("EXCO_BLENDER")
    if override and Path(override).exists():
        return override
    bundled = _bundled_blender()
    if bundled is not None:
        return str(bundled)
    return shutil.which("blender")


def blender_available() -> bool:
    return find_blender() is not None


def run_blender_script(script: str, workdir: Path) -> None:
    """Run a python script in one headless Blender process.

    Raises BlenderError with the tail of blender's output on failure.
    """
    exe = find_blender()
    if exe is None:
        raise BlenderError(
            "blender not found; set EXCO_BLENDER or install Blender >= 4.0"
        )
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
            [exe, "-b", "--factory-startup", "--python", str(runner_path)],
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
