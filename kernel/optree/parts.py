import hashlib
import json
from pathlib import Path

from optree.errors import OpTreeError


class PartsIndex:
    """Registry of library parts backed by <parts_dir>/index.json."""

    def __init__(self, parts: dict[str, dict], root: Path):
        self._parts = parts
        self._root = root

    @classmethod
    def load(cls, parts_dir: str | Path) -> "PartsIndex":
        # resolve to an absolute path: Blender subprocesses run with cwd=workdir
        root = Path(parts_dir).resolve()
        index_path = root / "index.json"
        if not index_path.exists():
            raise OpTreeError(f"parts index not found: {index_path}")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("parts", {}), dict):
            raise OpTreeError("invalid parts index: top-level 'parts' must be an object")
        parts = data.get("parts", {})
        for name, entry in parts.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
                raise OpTreeError(
                    f"invalid parts index entry {name!r}: needs a string 'file'"
                )
            glb = root / entry["file"]
            if not glb.exists():
                raise OpTreeError(f"part {name!r} file missing: {glb}")
        return cls(parts, root)

    def resolve(self, name: str) -> Path:
        if name not in self._parts:
            raise OpTreeError(
                f"unknown part {name!r}; available: {sorted(self._parts)}"
            )
        return self._root / self._parts[name]["file"]

    def content_hash(self, name: str) -> str:
        return hashlib.sha256(self.resolve(name).read_bytes()).hexdigest()[:16]

    def names(self) -> list[str]:
        return sorted(self._parts)

    def describe(self, name: str) -> str:
        """One-line part summary for the LLM prompt (description/mount/size)."""
        if name not in self._parts:
            raise OpTreeError(
                f"unknown part {name!r}; available: {sorted(self._parts)}"
            )
        entry = self._parts[name]
        desc = entry.get("description", "")
        snap = entry.get("snap") or {}
        mount = snap.get("mount", "unspecified")
        dims = snap.get("approx_size_m") or []
        size = "x".join(_fmt_dim(d) for d in dims) + "m" if dims else "unknown"
        return f"{name} — {desc}; mount: {mount}; size: {size}"


def _fmt_dim(x: float) -> str:
    return str(int(x)) if float(x) == int(x) else str(x)
