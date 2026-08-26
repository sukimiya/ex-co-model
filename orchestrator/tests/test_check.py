import json
from pathlib import Path

import pytest

from orchestrator.check import Verdict, vision_check
from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient


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
