import json
from pathlib import Path

import pytest

import orchestrator.check
from orchestrator.check import Verdict, self_check, vision_check
from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient
from orchestrator.session import Session

VALID_TREE = json.dumps({
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"],
                "params": {"filename": "ship.fbx"}},
    }
})


@pytest.fixture
def fake_render(tmp_path, monkeypatch):
    """Replace build_and_render with a stub that writes a fake png."""
    def stub(session, workdir, parts_dir):
        png = tmp_path / "preview.png"
        png.write_bytes(b"fake-png")
        return png
    monkeypatch.setattr(orchestrator.check, "build_and_render", stub)
    return stub


def test_vision_check_ok(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-png")
    llm = FakeLLMClient(['{"ok": true}'])
    v = vision_check(llm, png, "一艘护卫舰")
    assert v.ok and v.reason == ""
    assert llm.image_calls[0][1] == png  # image path passed through


def test_vision_check_not_ok_with_reason(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-png")
    llm = FakeLLMClient(['{"ok": false, "reason": "missing engines"}'])
    v = vision_check(llm, png, "双引擎护卫舰")
    assert not v.ok
    assert "engines" in v.reason


def test_vision_check_bad_json_raises(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-png")
    llm = FakeLLMClient(["looks fine to me"])
    with pytest.raises(OrchestratorError, match="invalid verdict"):
        vision_check(llm, png, "一艘护卫舰")


def test_vision_check_non_dict_json_raises(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-png")
    llm = FakeLLMClient(["[1]"])
    with pytest.raises(OrchestratorError, match="not an object"):
        vision_check(llm, png, "一艘护卫舰")


def test_self_check_passes_first_try(tmp_path, fake_render):
    session = Session(tmp_path / "s.json")
    llm = FakeLLMClient(['{"ok": true}'])
    msg = self_check(session, llm, "一艘护卫舰", tmp_path / "w", None)
    assert "passed" in msg
    assert len(llm.image_calls) == 1


def test_self_check_fail_then_pass_feeds_critique(tmp_path, fake_render):
    session = Session(tmp_path / "s.json")
    llm = FakeLLMClient([
        '{"ok": false, "reason": "missing engines"}',  # verdict 1
        VALID_TREE,                                     # critique re-apply
        '{"ok": true}',                                 # verdict 2
    ])
    msg = self_check(session, llm, "双引擎护卫舰", tmp_path / "w", None)
    assert "passed" in msg
    assert len(llm.image_calls) == 2
    # the re-apply's user message carries the critique reason
    assert "missing engines" in llm.calls[0][-1]["content"]


def test_self_check_exhaustion_keeps_last_result(tmp_path, fake_render):
    session = Session(tmp_path / "s.json")
    llm = FakeLLMClient([
        '{"ok": false, "reason": "bad hull"}', VALID_TREE,
        '{"ok": false, "reason": "bad hull"}', VALID_TREE,
        '{"ok": false, "reason": "still bad hull"}',
    ])
    msg = self_check(session, llm, "一艘护卫舰", tmp_path / "w", None)
    assert "keeping last result" in msg
    assert "still bad hull" in msg


class VisionUnavailableClient:
    """Test double whose vision endpoint always fails."""

    def __init__(self):
        self.image_calls = 0

    def complete(self, messages):
        raise AssertionError("not used")

    def complete_with_image(self, text, image_path):
        self.image_calls += 1
        raise OrchestratorError("vision endpoint down")


def test_self_check_vision_unavailable_skips(tmp_path, fake_render):
    session = Session(tmp_path / "s.json")
    llm = VisionUnavailableClient()
    msg = self_check(session, llm, "一艘护卫舰", tmp_path / "w", None)
    assert "vision check unavailable" in msg
    assert llm.image_calls == 1  # no retry
