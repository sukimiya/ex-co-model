import json
import threading
from http.client import HTTPConnection

import pytest

from orchestrator.llm import FakeLLMClient
from orchestrator.server import make_server
from tests.conftest import requires_blender

VALID_TREE = json.dumps({
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"],
                "params": {"filename": "ship.fbx"}},
    }
})


@pytest.fixture
def server(tmp_path):
    fake = FakeLLMClient([VALID_TREE, VALID_TREE])
    srv = make_server(tmp_path / "s.json", tmp_path / "w", None,
                      llm_factory=lambda: fake, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, fake
    srv.shutdown()
    thread.join()


def _get(srv, path):
    conn = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def _post(srv, path, payload):
    conn = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=120)
    conn.request("POST", path, json.dumps(payload),
                 {"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, json.loads(body)


def test_index_served(server):
    status, body = _get(server[0], "/")
    assert status == 200
    assert b"<title>" in body


@requires_blender
def test_state_empty_then_populated(server):
    srv, fake = server
    status, body = _get(srv, "/api/state")
    assert status == 200
    assert json.loads(body)["tree"] is None

    status, data = _post(srv, "/api/apply", {"instruction": "一艘护卫舰"})
    assert status == 200 and data["ok"] and data["nodes"] == 2

    status, body = _get(srv, "/api/state")
    state = json.loads(body)
    assert state["tree"] is not None and state["nodes"] == 2


def test_apply_error_is_structured(server):
    srv, fake = server
    fake.responses = ["garbage"] * 3
    status, data = _post(srv, "/api/apply", {"instruction": "x"})
    assert status == 200
    assert data["ok"] is False
    assert "error" in data


def test_404_for_unknown_path(server):
    status, _ = _get(server[0], "/nope")
    assert status == 404
