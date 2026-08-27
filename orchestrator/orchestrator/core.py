import json
from dataclasses import dataclass

from pydantic import ValidationError

from optree.errors import CycleError
from optree.graph import affected_subtree, topo_order
from optree.schema import OpTree

from orchestrator.errors import OrchestratorError
from orchestrator.llm import LLMClient
from orchestrator.prompts import build_messages, feedback_message


@dataclass
class ApplyResult:
    tree: OpTree
    rounds: int


def _validate(raw: str) -> OpTree:
    """Parse + schema-validate + dag-check an LLM response. Raises on failure."""
    tree = OpTree.model_validate(json.loads(raw))
    topo_order(tree)  # raises CycleError
    return tree


def _frozen_violations(old: OpTree, new: OpTree, focus: str) -> list[str]:
    """Node names that changed even though only `focus` + its downstream may change."""
    if focus not in new.nodes:
        return [focus]
    allowed = affected_subtree(new, {focus})
    out = []
    for name, node in old.nodes.items():
        if name in allowed:
            continue
        if name not in new.nodes or new.nodes[name].model_dump() != node.model_dump():
            out.append(name)
    return out


def run_apply(llm: LLMClient, instruction: str, current_tree: OpTree | None,
              max_rounds: int = 3,
              available_parts: list[str] | None = None,
              focus_node: str | None = None) -> ApplyResult:
    """Ask the LLM for an OpTree; feed validation errors back up to max_rounds.
    With focus_node, every node outside the focus subtree must stay byte-identical."""
    if focus_node is not None and (current_tree is None or focus_node not in current_tree.nodes):
        raise OrchestratorError(f"focus node {focus_node!r} not in current tree")
    messages = build_messages(instruction, current_tree, available_parts,
                              focus_node=focus_node)
    last_error: str | None = None
    for round_no in range(1, max_rounds + 1):
        raw = llm.complete(messages)
        try:
            tree = _validate(raw)
        except (json.JSONDecodeError, ValidationError, CycleError) as e:
            last_error = str(e)
        else:
            if focus_node is None:
                return ApplyResult(tree=tree, rounds=round_no)
            bad = _frozen_violations(current_tree, tree, focus_node)
            if not bad:
                return ApplyResult(tree=tree, rounds=round_no)
            last_error = (
                f"nodes {bad} are frozen: only node {focus_node!r}, its downstream "
                "dependents, and new nodes may change; restore the frozen nodes "
                "byte-identical"
            )
        messages.append({"role": "assistant", "content": raw})
        messages.append(feedback_message(last_error))
    raise OrchestratorError(
        f"llm failed to produce a valid optree after {max_rounds} rounds: {last_error}"
    )
