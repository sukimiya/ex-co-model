from optree.errors import CycleError
from optree.schema import OpTree


def _dependents(tree: OpTree) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {name: [] for name in tree.nodes}
    for name, node in tree.nodes.items():
        for ref in node.inputs:
            deps[ref].append(name)
    return deps


def topo_order(tree: OpTree) -> list[str]:
    """Kahn's algorithm. Raises CycleError if the graph has a cycle."""
    indegree = {name: len(node.inputs) for name, node in tree.nodes.items()}
    dependents = _dependents(tree)
    ready = sorted(n for n, d in indegree.items() if d == 0)
    order: list[str] = []
    while ready:
        name = ready.pop(0)
        order.append(name)
        for dep in dependents[name]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)
    if len(order) != len(tree.nodes):
        raise CycleError("optree contains a dependency cycle")
    return order


def affected_subtree(tree: OpTree, changed: set[str]) -> set[str]:
    """Return `changed` plus every node that (transitively) depends on them."""
    unknown = changed - set(tree.nodes)
    if unknown:
        raise ValueError(f"unknown nodes: {sorted(unknown)}")
    dependents = _dependents(tree)
    seen = set(changed)
    stack = list(changed)
    while stack:
        for dep in dependents[stack.pop()]:
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen
