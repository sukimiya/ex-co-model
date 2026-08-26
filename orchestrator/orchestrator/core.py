import json
from dataclasses import dataclass

from pydantic import ValidationError

from optree.errors import CycleError
from optree.graph import topo_order
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


def run_apply(llm: LLMClient, instruction: str, current_tree: OpTree | None,
              max_rounds: int = 3) -> ApplyResult:
    """Ask the LLM for an OpTree; feed validation errors back up to max_rounds."""
    messages = build_messages(instruction, current_tree)
    last_error: str | None = None
    for round_no in range(1, max_rounds + 1):
        raw = llm.complete(messages)
        try:
            tree = _validate(raw)
        except (json.JSONDecodeError, ValidationError, CycleError) as e:
            last_error = str(e)
            messages.append({"role": "assistant", "content": raw})
            messages.append(feedback_message(last_error))
            continue
        return ApplyResult(tree=tree, rounds=round_no)
    raise OrchestratorError(
        f"llm failed to produce a valid optree after {max_rounds} rounds: {last_error}"
    )
