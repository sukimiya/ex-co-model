import pytest

from optree.errors import CycleError
from optree.graph import affected_subtree, topo_order
from optree.schema import OpTree


def make_tree(edges: dict[str, dict]) -> OpTree:
    return OpTree.model_validate({"nodes": edges})


def chain_tree() -> OpTree:
    return make_tree({
        "a": {"op": "primitive", "params": {"type": "box"}},
        "b": {"op": "bevel", "inputs": ["a"]},
        "c": {"op": "scale_to", "inputs": ["b"], "params": {"length_m": 28}},
    })


def test_topo_order_linear_chain():
    order = topo_order(chain_tree())
    assert order.index("a") < order.index("b") < order.index("c")


def test_topo_order_diamond():
    tree = make_tree({
        "base": {"op": "primitive", "params": {"type": "box"}},
        "cutter": {"op": "primitive", "params": {"type": "box"}},
        "cut": {"op": "boolean_subtract", "inputs": ["base", "cutter"]},
        "out": {"op": "export_fbx", "inputs": ["cut"]},
    })
    order = topo_order(tree)
    assert order.index("base") < order.index("cut")
    assert order.index("cutter") < order.index("cut")
    assert order[-1] == "out"


def test_cycle_raises():
    # schema only checks that referenced nodes exist; graph is responsible for catching cycles
    tree = OpTree.model_validate({
        "nodes": {
            "a": {"op": "bevel", "inputs": ["b"]},
            "b": {"op": "bevel", "inputs": ["a"]},
        }
    })
    with pytest.raises(CycleError):
        topo_order(tree)


def test_affected_subtree_returns_downstream():
    assert affected_subtree(chain_tree(), {"a"}) == {"a", "b", "c"}
    assert affected_subtree(chain_tree(), {"b"}) == {"b", "c"}
    assert affected_subtree(chain_tree(), {"c"}) == {"c"}


def test_affected_subtree_unknown_node_raises():
    with pytest.raises(ValueError, match="unknown"):
        affected_subtree(chain_tree(), {"zzz"})
