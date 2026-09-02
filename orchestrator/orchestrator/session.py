import json
import os
from pathlib import Path

from optree.schema import OpTree

from orchestrator.core import ApplyResult, run_apply
from orchestrator.llm import LLMClient


class Session:
    """One asset under editing. The session file IS the OpTree json."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.tree: OpTree | None = None
        if self.path.exists():
            self.tree = OpTree.model_validate(
                json.loads(self.path.read_text(encoding="utf-8"))
            )

    def apply(self, llm: LLMClient, instruction: str,
              available_parts: list[str] | None = None,
              focus_node: str | None = None) -> ApplyResult:
        result = run_apply(llm, instruction, self.tree,
                           available_parts=available_parts, focus_node=focus_node)
        previous = self.tree
        self.tree = result.tree
        try:
            self.save()
        except Exception:
            self.tree = previous  # failed write: keep memory consistent with disk
            raise
        return result

    def save(self) -> None:
        """Atomically persist the current tree (same format apply uses)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"nodes": {k: v.model_dump(exclude_defaults=True)
                           for k, v in self.tree.nodes.items()}},
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
