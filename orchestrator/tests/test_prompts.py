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


def test_system_prompt_documents_attach_part_rules():
    assert "attach_part" in SYSTEM_PROMPT
    # the anti-misuse rule: boolean_subtract is only for cutting
    assert "never" in SYSTEM_PROMPT.lower() or "only" in SYSTEM_PROMPT.lower()


def test_build_messages_lists_available_parts():
    msgs = build_messages("加一门炮", None, available_parts=["pdc_turret", "engine_nozzle"])
    assert "pdc_turret" in msgs[1]["content"]
    assert "engine_nozzle" in msgs[1]["content"]


def test_build_messages_shows_part_metadata():
    """Part entries carry description/mount/size one-liners, not bare names."""
    msgs = build_messages("加一门炮", None, available_parts=[
        "pdc_turret — point defense turret; mount: flat surface; size: 1x1x1m",
    ])
    user = msgs[1]["content"]
    assert "pdc_turret — point defense turret" in user
    assert "mount: flat surface" in user
    assert "size: 1x1x1m" in user


def test_build_messages_without_parts_omits_section():
    msgs = build_messages("一艘船", None)
    assert "Available parts" not in msgs[1]["content"]


def test_build_messages_with_focus_node():
    msgs = build_messages("make it taller", sample_tree(), focus_node="mast")
    assert "Focus node: mast" in msgs[-1]["content"]
    assert "byte-identical" in msgs[-1]["content"]
