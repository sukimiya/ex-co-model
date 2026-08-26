from optree.schema import OpTree

from orchestrator.prompts import SYSTEM_PROMPT, build_messages, feedback_message


def sample_tree() -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "out": {"op": "export_fbx", "inputs": ["hull"], "params": {"filename": "ship.fbx"}},
        }
    })


def test_system_prompt_documents_all_v1_ops():
    for op in ["primitive", "bevel", "boolean_subtract", "scale_to", "export_fbx"]:
        assert op in SYSTEM_PROMPT
    assert "json" in SYSTEM_PROMPT.lower()


def test_build_messages_without_tree_is_create_mode():
    msgs = build_messages("一艘双引擎护卫舰", None)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "一艘双引擎护卫舰" in msgs[1]["content"]
    assert "Current OpTree" not in msgs[1]["content"]


def test_build_messages_with_tree_embeds_current_json():
    msgs = build_messages("把船加长到40米", sample_tree())
    user = msgs[1]["content"]
    assert "Current OpTree" in user
    assert '"hull"' in user
    assert "把船加长到40米" in user


def test_feedback_message_wraps_error():
    msg = feedback_message("node 'a' references unknown node 'zz'")
    assert msg["role"] == "user"
    assert "references unknown node" in msg["content"]
    assert "corrected" in msg["content"].lower()
