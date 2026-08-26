import json
from dataclasses import dataclass
from pathlib import Path

from orchestrator.errors import OrchestratorError
from orchestrator.llm import LLMClient

CHECK_PROMPT = """\
You are the quality checker of ex-co-model, an AI 3D modeling tool. The user \
asked for: "{instruction}"
Look at the rendered preview of the produced model. Judge ONLY structure: are \
the requested parts present and the proportions plausible? Ignore \
textures/colors entirely (models are untextured by design at this stage).
Respond with one json object: {{"ok": true}} or \
{{"ok": false, "reason": "<what is wrong, concretely>"}}.\
"""


@dataclass
class Verdict:
    ok: bool
    reason: str = ""


def vision_check(llm: LLMClient, png: Path, instruction: str) -> Verdict:
    raw = llm.complete_with_image(
        CHECK_PROMPT.format(instruction=instruction), png)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise OrchestratorError(f"invalid verdict json from vision model: {e}")
    return Verdict(ok=bool(data.get("ok")), reason=str(data.get("reason", "")))
