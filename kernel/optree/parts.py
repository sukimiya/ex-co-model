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
        root = Path(parts_dir)
        index_path = root / "index.json"
        if not index_path.exists():
            raise OpTreeError(f"parts index not found: {index_path}")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        parts = data.get("parts", {})
        for name, entry in parts.items():
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
