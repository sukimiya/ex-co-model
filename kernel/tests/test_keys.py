from optree.keys import node_key
from optree.schema import OpTree


def two_trees(bevel_width: float) -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "a": {"op": "primitive", "params": {"type": "box"}},
            "b": {"op": "bevel", "inputs": ["a"], "params": {"width": bevel_width}},
        }
    })


def test_same_node_same_key():
    tree = two_trees(0.1)
    k1 = node_key(tree.nodes["a"], [])
    k2 = node_key(tree.nodes["a"], [])
    assert k1 == k2
    assert len(k1) == 16


def test_param_change_changes_key():
    k1 = node_key(two_trees(0.1).nodes["b"], ["x"])
    k2 = node_key(two_trees(0.2).nodes["b"], ["x"])
    assert k1 != k2


def test_input_key_change_changes_key():
    node = two_trees(0.1).nodes["b"]
    assert node_key(node, ["x"]) != node_key(node, ["y"])
