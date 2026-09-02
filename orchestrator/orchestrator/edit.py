"""Deterministic OpTree mutations for manual (non-LLM) editing."""

from optree.graph import topo_order
from optree.schema import OpTree

from orchestrator.errors import OrchestratorError


def _validated(nodes: dict) -> OpTree:
    tree = OpTree.model_validate({"nodes": nodes})
    topo_order(tree)  # cycle check, same gate as the LLM path
    return tree


def _dump(tree: OpTree) -> dict:
    return {k: v.model_dump() for k, v in tree.nodes.items()}


def _node_or_raise(tree: OpTree, node_id: str):
    if node_id not in tree.nodes:
        raise OrchestratorError(f"unknown node {node_id!r}")
    return tree.nodes[node_id]


def add_part(tree: OpTree, node_id: str, part: str, parent: str,
             location, rotation_deg, scale) -> OpTree:
    nodes = _dump(tree)
    if node_id in nodes:
        raise OrchestratorError(f"node {node_id!r} already exists")
    _node_or_raise(tree, parent)
    nodes[node_id] = {
        "op": "attach_part", "inputs": [parent],
        "params": {"part": part, "location": list(location),
                   "rotation_deg": list(rotation_deg), "scale": scale},
    }
    return _validated(nodes)


def update_transform(tree: OpTree, node_id: str, *, location=None,
                     rotation_deg=None, scale=None) -> OpTree:
    node = _node_or_raise(tree, node_id)
    if node.op != "attach_part":
        raise OrchestratorError(
            f"node {node_id!r} is {node.op}; only attach_part can be transformed")
    nodes = _dump(tree)
    p = nodes[node_id]["params"]
    if location is not None:
        p["location"] = list(location)
    if rotation_deg is not None:
        p["rotation_deg"] = list(rotation_deg)
    if scale is not None:
        p["scale"] = scale
    return _validated(nodes)


def remove_node(tree: OpTree, node_id: str) -> OpTree:
    node = _node_or_raise(tree, node_id)
    nodes = _dump(tree)
    fallback = node.inputs[0] if node.inputs else None
    if fallback is None:
        referenced_by = [name for name, child in nodes.items()
                         if name != node_id and node_id in child["inputs"]]
        if referenced_by:
            raise OrchestratorError(
                f"cannot remove {node_id!r}: still referenced and has no input")
    del nodes[node_id]
    for child in nodes.values():
        child["inputs"] = [
            (fallback if ref == node_id else ref) for ref in child["inputs"]
        ]
    return _validated(nodes)


def cut_slot(tree: OpTree, node_id: str, target: str,
             size, location) -> OpTree:
    nodes = _dump(tree)
    if node_id in nodes or f"{node_id}_cutter" in nodes:
        raise OrchestratorError(f"node {node_id!r} already exists")
    _node_or_raise(tree, target)
    nodes[f"{node_id}_cutter"] = {
        "op": "primitive",
        "params": {"type": "box", "size": list(size), "location": list(location)},
    }
    nodes[node_id] = {
        "op": "boolean_subtract", "inputs": [target, f"{node_id}_cutter"],
    }
    return _validated(nodes)
