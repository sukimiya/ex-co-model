from __future__ import annotations

import os
from typing import Protocol

from openai import OpenAI

from orchestrator.errors import OrchestratorError

DEFAULT_MODEL = "kimi-k2-0711-preview"
DEFAULT_BASE_URL = "https://api.moonshot.ai/v1"


class LLMClient(Protocol):
    """Anything that can complete a chat message list and return raw text."""

    def complete(self, messages: list[dict]) -> str: ...


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
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=base_url or os.environ.get("MOONSHOT_BASE_URL", DEFAULT_BASE_URL),
        )

    def complete(self, messages: list[dict]) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content


class FakeLLMClient:
    """Test double: returns queued responses in order and records calls."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("FakeLLMClient ran out of queued responses")
        return self.responses.pop(0)
