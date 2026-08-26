from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import openai
from openai import OpenAI

from orchestrator.errors import OrchestratorError

DEFAULT_MODEL = "kimi-k2-0711-preview"
DEFAULT_BASE_URL = "https://api.moonshot.ai/v1"


class LLMClient(Protocol):
    """Anything that can complete a chat message list and return raw text."""

    def complete(self, messages: list[dict]) -> str: ...

    def complete_with_image(self, text: str, image_path: Path) -> str: ...


class MoonshotClient:
    """Moonshot/Kimi client via the OpenAI-compatible API."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None):
        self.api_key = api_key or os.environ.get("MOONSHOT_API_KEY")
        if not self.api_key:
            raise OrchestratorError(
                "MOONSHOT_API_KEY not set; export it before using the orchestrator"
            )
        self.model = model or os.environ.get("MOONSHOT_MODEL", DEFAULT_MODEL)
        # Some providers (e.g. api.kimi.com/coding) reject any explicit
        # temperature; only send it when the user opts in via env var.
        raw_temp = os.environ.get("MOONSHOT_TEMPERATURE")
        self.temperature = float(raw_temp) if raw_temp is not None else None
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=base_url or os.environ.get("MOONSHOT_BASE_URL", DEFAULT_BASE_URL),
        )

    def complete(self, messages: list[dict]) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as e:
            raise OrchestratorError(f"llm request failed: {e}") from e
        if not resp.choices or resp.choices[0].message.content is None:
            raise OrchestratorError("llm returned an empty response")
        return resp.choices[0].message.content

    def complete_with_image(self, text: str, image_path: Path) -> str:
        import base64
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        kwargs: dict = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as e:
            raise OrchestratorError(f"llm request failed: {e}") from e
        if not resp.choices or resp.choices[0].message.content is None:
            raise OrchestratorError("llm returned an empty response")
        return resp.choices[0].message.content


class FakeLLMClient:
    """Test double: returns queued responses in order and records calls."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []
        self.image_calls: list[tuple[str, Path]] = []

    def complete(self, messages: list[dict]) -> str:
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("FakeLLMClient ran out of queued responses")
        return self.responses.pop(0)

    def complete_with_image(self, text: str, image_path) -> str:
        self.image_calls.append((text, image_path))
        if not self.responses:
            raise AssertionError("FakeLLMClient ran out of queued responses")
        return self.responses.pop(0)
