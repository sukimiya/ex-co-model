import json
from dataclasses import dataclass
from pathlib import Path

from orchestrator.errors import OrchestratorError
from orchestrator.llm import LLMClient
from orchestrator.pipeline import build_and_render
from orchestrator.session import Session

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
    if not isinstance(data, dict):
        raise OrchestratorError(
            "invalid verdict json from vision model: not an object")
    return Verdict(ok=bool(data.get("ok")), reason=str(data.get("reason", "")))


def self_check(session: Session, llm: LLMClient, instruction: str,
               workdir: Path, parts_dir: Path | None,
               available_parts: list[str] | None = None,
               max_retries: int = 2) -> str:
    """Build+render+vision-check, retrying with critique. Returns a status message.
    Raises OrchestratorError only for build/pipeline failures; vision transport
    failures degrade to a 'skipped' status message."""
    for _attempt in range(max_retries + 1):
        png = build_and_render(session, workdir, parts_dir)
        try:
            verdict = vision_check(llm, png, instruction)
        except OrchestratorError as e:
            return f"warning: vision check unavailable: {e}"
        if verdict.ok:
            return "self-check passed"
        if _attempt < max_retries:
            critique = (f"The rendered result is wrong: {verdict.reason}. "
                        f"Original request: {instruction}")
            session.apply(llm, critique, available_parts=available_parts)
        else:
            return (f"warning: self-check still failing after {max_retries} "
                    f"retries: {verdict.reason}; keeping last result")
    raise AssertionError("unreachable")
