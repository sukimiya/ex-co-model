import json
import threading
import types
from http.client import HTTPConnection

import pytest
from optree.errors import OpTreeError

from orchestrator.llm import FakeLLMClient
from orchestrator.server import make_server


def _tree(session_path):
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps({"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "out": {"op": "export_fbx", "inputs": ["hull"]},
    }}), encoding="utf-8")


def _parts_dir(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "turret.glb").write_bytes(b"glTF-part-bytes")
    (root / "index.json").write_text(json.dumps({"parts": {
        "pdc_turret": {
            "file": "turret.glb",
            "description": "point defense turret",
            "snap": {"mount": "flat surface", "approx_size_m": [1.2, 1.2, 1.6]},
            "snap_points": [{"position": [0, 0, 0.8], "normal": [0, 0, 1]}],
        },
    }}), encoding="utf-8")
    return root


def _boot(tmp_path, monkeypatch, parts_dir=None):
    """Boot a real server with build/render stubbed so no Blender runs."""
    session_path = tmp_path / "s.json"
    _tree(session_path)
    glb = tmp_path / "w" / "stub.glb"
    glb.parent.mkdir(parents=True, exist_ok=True)
    glb.write_bytes(b"glTF-stub")
    calls = {"build": 0, "render": 0}

    def fake_build(tree, workdir, parts_dir=None):
        calls["build"] += 1
        return types.SimpleNamespace(glbs={name: glb for name in tree.nodes})

    def fake_render(glb_path, out_path, workdir):
        calls["render"] += 1
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG-stub")
        return out_path

    monkeypatch.setattr("orchestrator.server.build", fake_build)
    monkeypatch.setattr("orchestrator.server.render_glb", fake_render)
    srv = make_server(session_path, tmp_path / "w", parts_dir,
                      llm_factory=lambda: FakeLLMClient([]), port=0,
                      settings_path=tmp_path / "settings.json")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, session_path, calls, thread


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv, session_path, calls, thread = _boot(tmp_path, monkeypatch)
    yield srv, session_path, calls
    srv.shutdown()
    thread.join()


@pytest.fixture
def parts_server(tmp_path, monkeypatch):
    srv, session_path, calls, thread = _boot(
        tmp_path, monkeypatch, parts_dir=_parts_dir(tmp_path / "parts"))
    yield srv, session_path, calls
    srv.shutdown()
    thread.join()


def _get(srv, path):
    conn = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    ctype = resp.getheader("Content-Type")
    conn.close()
    return resp.status, body, ctype


def _post(srv, path, payload):
    conn = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    conn.request("POST", path, json.dumps(payload),
                 {"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, json.loads(body)


def _add_turret(srv):
    return _post(srv, "/api/edit", {
        "op": "add_part", "node_id": "turret", "part": "pdc_turret",
        "parent": "hull", "location": [0, 0, 3],
        "rotation_deg": [0, 0, 0], "scale": 1.0})


def test_api_edit_add_part(server):
    srv, session_path, calls = server
    status, data = _add_turret(srv)
    assert status == 200 and data["ok"] is True
    node = data["tree"]["nodes"]["turret"]
    assert node["op"] == "attach_part"
    assert node["inputs"] == ["hull"]
    assert node["params"]["part"] == "pdc_turret"
    # like /api/apply: build + preview render happen after the edit
    assert calls == {"build": 1, "render": 1}
    # the edit is persisted to the session file
    saved = json.loads(session_path.read_text(encoding="utf-8"))
    assert saved["nodes"]["turret"]["inputs"] == ["hull"]


def test_api_edit_update_transform(server):
    srv, _, _ = server
    _add_turret(srv)
    status, data = _post(srv, "/api/edit", {
        "op": "update_transform", "node_id": "turret",
        "location": [1, 2, 3]})
    assert status == 200 and data["ok"] is True
    params = data["tree"]["nodes"]["turret"]["params"]
    assert params["location"] == [1, 2, 3]
    assert params["part"] == "pdc_turret"  # untouched


def test_api_edit_remove_node_rewires(server):
    srv, session_path, _ = server
    session_path.write_text(json.dumps({"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "cutter": {"op": "primitive", "params": {"type": "box", "size": [1, 1, 1]}},
        "slot": {"op": "boolean_subtract", "inputs": ["hull", "cutter"]},
        "out": {"op": "export_fbx", "inputs": ["slot"]},
    }}), encoding="utf-8")
    status, data = _post(srv, "/api/edit", {"op": "remove_node", "node_id": "slot"})
    assert status == 200 and data["ok"] is True
    nodes = data["tree"]["nodes"]
    assert "slot" not in nodes
    assert nodes["out"]["inputs"] == ["hull"]


def test_api_edit_cut_slot(server):
    srv, _, _ = server
    status, data = _post(srv, "/api/edit", {
        "op": "cut_slot", "node_id": "slot1", "target": "hull",
        "size": [1, 1, 1], "location": [0, 0, 0]})
    assert status == 200 and data["ok"] is True
    nodes = data["tree"]["nodes"]
    assert nodes["slot1"]["op"] == "boolean_subtract"
    assert nodes["slot1"]["inputs"] == ["hull", "slot1_cutter"]
    assert nodes["slot1_cutter"]["op"] == "primitive"


def test_api_edit_unknown_op(server):
    srv, _, calls = server
    status, data = _post(srv, "/api/edit", {"op": "explode"})
    assert status == 200
    assert data["ok"] is False
    assert "explode" in data["error"]
    assert calls == {"build": 0, "render": 0}  # failed edits don't rebuild


def test_api_edit_build_failure_does_not_persist(server, monkeypatch):
    srv, session_path, _ = server

    def boom(tree, workdir, parts_dir=None):
        raise OpTreeError("blender exploded")

    monkeypatch.setattr("orchestrator.server.build", boom)
    before = session_path.read_text(encoding="utf-8")
    status, data = _add_turret(srv)
    assert status == 200 and data["ok"] is False
    assert "blender exploded" in data["error"]
    # the failed edit is not persisted; disk and response stay consistent
    assert session_path.read_text(encoding="utf-8") == before


def test_api_snap_within_radius(server):
    srv, _, _ = server
    status, data = _post(srv, "/api/snap", {
        "part": "pdc_turret",
        "target_point": [0, 0, 1.9], "target_normal": [0, 0, 1],
        "candidates": [{"position": [0, 0, 2], "normal": [0, 0, 1]}]})
    assert status == 200
    assert data["snapped"] is True
    assert data["snap_point"] == [0, 0, 2]
    assert data["location"] == [0, 0, 2]
    assert data["rotation_deg"] == [0, 0, 0]  # +z normal needs no rotation


def test_api_snap_outside_radius(server):
    srv, _, _ = server
    status, data = _post(srv, "/api/snap", {
        "part": "pdc_turret",
        "target_point": [50, 0, 0], "target_normal": [0, 0, 1],
        "candidates": [{"position": [0, 0, 2], "normal": [0, 0, 1]}]})
    assert status == 200
    assert data["snapped"] is False


def test_api_parts(parts_server):
    srv, _, _ = parts_server
    status, body, _ = _get(srv, "/api/parts")
    assert status == 200
    parts = json.loads(body)["parts"]
    assert len(parts) == 1
    part = parts[0]
    assert part["name"] == "pdc_turret"
    assert part["description"] == "point defense turret"
    assert part["approx_size_m"] == [1.2, 1.2, 1.6]
    assert part["snap_points"] == [{"position": [0, 0, 0.8], "normal": [0, 0, 1]}]


def test_api_parts_empty_without_parts_dir(server):
    srv, _, _ = server
    status, body, _ = _get(srv, "/api/parts")
    assert status == 200
    assert json.loads(body)["parts"] == []


def test_part_glb_serves_bytes(parts_server):
    srv, _, _ = parts_server
    status, body, ctype = _get(srv, "/part.glb?name=pdc_turret")
    assert status == 200
    assert body == b"glTF-part-bytes"
    assert ctype == "model/gltf-binary"


def test_part_glb_unknown_part_is_404(parts_server):
    srv, _, _ = parts_server
    status, _, _ = _get(srv, "/part.glb?name=railgun")
    assert status == 404
