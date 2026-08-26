import hashlib
import json

from optree.schema import Node


def node_key(node: Node, input_keys: list[str]) -> str:
    """Content hash of op + params + input keys. Deterministic."""
    raw = node.model_dump()
    payload = {
        "op": node.op,
        "params": raw.get("params", {}),
        "inputs": input_keys,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
