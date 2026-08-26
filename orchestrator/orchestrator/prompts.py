import json

from optree.schema import OpTree

SYSTEM_PROMPT = """\
You are the modeling planner of ex-co-model, an AI-driven parametric 3D modeling \
tool for game assets. You never touch meshes directly. You read and write ONLY \
the OpTree: a JSON document describing modeling operations as a DAG.

Output contract:
- Respond with ONE json object: {"nodes": {<name>: <node>, ...}}. No prose.
- Every node: {"op": <op>, "inputs": [<node names>], "params": {...}}; omit "params" entirely for boolean_subtract (it has none).
- inputs reference other node names; every reference must exist; no cycles.
- Units are meters. Keep the final export_fbx node pointing at the final geometry.

Node types (v1):
- primitive: no inputs. params: type ("box"|"cylinder"), size [x,y,z] (box, full \
extents), radius/depth/vertices (cylinder), location [x,y,z].
- bevel: inputs [src]. params: width, segments.
- boolean_subtract: inputs [target, cutter]. Cut a slot/hole out of target.
- scale_to: inputs [src]. params: length_m (>0). Uniformly scales so the longest \
axis equals length_m.
- export_fbx: inputs [src]. params: filename (plain basename ending in .fbx).

When modifying an existing tree, change only what the instruction requires and \
keep every unrelated node byte-identical (names, params, structure).\
"""


def build_messages(instruction: str, current_tree: OpTree | None) -> list[dict]:
    user = ""
    if current_tree is not None:
        tree_json = json.dumps(
            {"nodes": {k: v.model_dump(exclude_defaults=True)
                       for k, v in current_tree.nodes.items()}},
            indent=2,
        )
        user += f"Current OpTree:\n```json\n{tree_json}\n```\n\n"
    user += f"Instruction: {instruction}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def feedback_message(error: str) -> dict:
    """User-role message feeding a validation error back to the LLM."""
    return {
        "role": "user",
        "content": (
            f"The OpTree you produced is invalid. Error: {error}\n"
            "Return a corrected complete OpTree json object only."
        ),
    }
