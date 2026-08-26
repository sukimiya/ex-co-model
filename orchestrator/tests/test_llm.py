import pytest

from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient, MoonshotClient


def test_moonshot_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    with pytest.raises(OrchestratorError, match="MOONSHOT_API_KEY"):
        MoonshotClient()


def test_moonshot_client_calls_openai_compatible_api(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            class Msg:
                content = '{"nodes": {}}'
            class Choice:
                message = Msg()
            class Resp:
                choices = [Choice()]
            return Resp()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("orchestrator.llm.OpenAI", FakeOpenAI)
    client = MoonshotClient(api_key="sk-test", model="kimi-k2-0711-preview")
    out = client.complete([{"role": "user", "content": "hi"}])
    assert out == '{"nodes": {}}'
    assert captured["model"] == "kimi-k2-0711-preview"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_moonshot_client_reads_env(monkeypatch):
    monkeypatch.setattr("orchestrator.llm.OpenAI", lambda api_key, base_url: None)
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-env")
    monkeypatch.delenv("MOONSHOT_MODEL", raising=False)
    monkeypatch.delenv("MOONSHOT_BASE_URL", raising=False)
    client = MoonshotClient()
    assert client.api_key == "sk-env"
    assert client.model == "kimi-k2-0711-preview"


def test_fake_llm_client_queues_and_records():
    fake = FakeLLMClient(["resp1", "resp2"])
    assert fake.complete([{"role": "user", "content": "a"}]) == "resp1"
    assert fake.complete([{"role": "user", "content": "b"}]) == "resp2"
    assert len(fake.calls) == 2
    with pytest.raises(AssertionError, match="ran out"):
        fake.complete([])
