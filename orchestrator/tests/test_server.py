import json
import socket
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


def test_apply_passes_focus_node(server, monkeypatch):
    srv, _ = server
    captured = {}

    def fake_apply(self, llm, instruction, available_parts=None,
                   focus_node=None):
        captured["focus_node"] = focus_node
        # Stop before build so no Blender is needed.
        raise ValueError("stop before build")

    monkeypatch.setattr("orchestrator.session.Session.apply", fake_apply)
    status, data = _post(srv, "/api/apply",
                         {"instruction": "给桅杆加天线", "node": "mast"})
    assert status == 200 and data["ok"] is False
    assert captured["focus_node"] == "mast"


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


@requires_blender
def test_apply_then_model_glb_and_preview_build_once(server):
    srv, fake = server
    status, data = _post(srv, "/api/apply", {"instruction": "一艘护卫舰"})
    assert status == 200 and data["ok"]

    status, body = _get(srv, "/model.glb")
    assert status == 200
    assert body[:4] == b"glTF"

    status, body = _get(srv, "/preview.png")
    assert status == 200
    assert body[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def corrupt_server(tmp_path):
    session_path = tmp_path / "s.json"
    session_path.write_text("not json at all", encoding="utf-8")
    srv = make_server(session_path, tmp_path / "w", None,
                      llm_factory=lambda: FakeLLMClient([]), port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    thread.join()


def test_state_corrupt_session_returns_structured_error(corrupt_server):
    status, body = _get(corrupt_server, "/api/state")
    state = json.loads(body)
    assert status == 200
    assert state["tree"] is None and state["nodes"] == 0
    assert "error" in state


def test_model_glb_corrupt_session_returns_500(corrupt_server):
    status, body = _get(corrupt_server, "/model.glb")
    assert status == 500
    assert body.startswith(b"error:")


def test_post_bad_content_length_is_structured(server):
    srv, _ = server
    sock = socket.create_connection(("127.0.0.1", srv.server_address[1]),
                                    timeout=10)
    try:
        sock.sendall(b"POST /api/apply HTTP/1.1\r\nHost: x\r\n"
                     b"Content-Type: application/json\r\n"
                     b"Content-Length: abc\r\n\r\n")
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
    finally:
        sock.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    assert b"200" in head.split(b"\r\n", 1)[0]
    assert json.loads(body)["ok"] is False
