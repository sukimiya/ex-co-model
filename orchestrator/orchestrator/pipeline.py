from pathlib import Path

from optree.engine import BuildResult, build
from optree.graph import topo_order
from optree.render import render_glb
from optree.schema import OpTree

from orchestrator.errors import OrchestratorError
from orchestrator.session import Session


def final_glb(tree: OpTree, result: BuildResult) -> Path:
    """The glb representing the finished asset (input of the export node)."""
    for node in tree.nodes.values():
        if node.op == "export_fbx":
            return result.glbs[node.inputs[0]]
    return result.glbs[topo_order(tree)[-1]]


def build_and_render(session: Session, workdir: Path,
                     parts_dir: Path | None) -> Path:
    """Build the session tree and render a preview png. Returns the png path."""
    if session.tree is None:
        raise OrchestratorError(f"no session tree at {session.path}")
    result = build(session.tree, workdir, parts_dir=parts_dir)
    return render_glb(final_glb(session.tree, result),
                      Path(workdir) / "out" / "preview.png", workdir)
