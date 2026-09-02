"""Local web UI: stdlib http server + three.js frontend. Single user, localhost."""

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from optree.engine import build
from optree.errors import OpTreeError
from optree.parts import PartsIndex
from optree.render import render_glb
from pydantic import ValidationError

from orchestrator.config import SETTINGS_KEYS, load_settings, save_settings
from orchestrator.edit import add_part, cut_slot, remove_node, update_transform
from orchestrator.errors import OrchestratorError
from orchestrator.paths import user_data_dir
from orchestrator.pipeline import final_glb
from orchestrator.session import Session
from orchestrator.snap import align_rotation_deg, snap_position

STATIC_DIR = Path(__file__).parent / "static"

PRESETS = [
    {"label": "Kimi Code", "endpoint": "https://api.kimi.com/coding/v1", "model": "kimi-for-coding"},
    {"label": "Kimi (Moonshot)", "endpoint": "https://api.moonshot.ai/v1", "model": "kimi-k2-0711-preview"},
    {"label": "DeepSeek", "endpoint": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"label": "OpenAI", "endpoint": "https://api.openai.com/v1", "model": "gpt-4o"},
]


class _State:
    def __init__(self, session_path: Path, workdir: Path,
                 parts_dir: Path | None, llm_factory,
                 settings_path: Path | None = None):
        self.session_path = Path(session_path)
        self.workdir = Path(workdir)
        self.parts_dir = parts_dir
        self.llm_factory = llm_factory
        self.built = False  # whether model.glb/preview are up to date
        self._settings_path = Path(settings_path) if settings_path else None

    def settings_path(self) -> Path:
        if self._settings_path is None:
            self._settings_path = user_data_dir() / "settings.json"
        return self._settings_path

    def part_names(self) -> list[str] | None:
        if self.parts_dir and Path(self.parts_dir).exists():
            idx = PartsIndex.load(self.parts_dir)
            return [idx.describe(n) for n in idx.names()]
        return None


def make_server(session_path, workdir, parts_dir, llm_factory,
                host="127.0.0.1", port=8787,
                settings_path: Path | None = None) -> ThreadingHTTPServer:
    state = _State(session_path, workdir, parts_dir, llm_factory,
                   settings_path=settings_path)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, obj):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            if self.path == "/":
                self._send(200, (STATIC_DIR / "index.html").read_bytes(),
                           "text/html; charset=utf-8")
            elif self.path == "/api/state":
                try:
                    session = Session(state.session_path)
                except (json.JSONDecodeError, ValidationError,
                        OrchestratorError) as e:
                    self._send_json(200, {"tree": None, "nodes": 0,
                                          "error": str(e)})
                    return
                tree = None
                if session.tree is not None:
                    tree = {"nodes": {
                        k: v.model_dump(exclude_defaults=True)
                        for k, v in session.tree.nodes.items()}}
                self._send_json(200, {
                    "tree": tree,
                    "nodes": len(tree["nodes"]) if tree else 0,
                    "parts": state.part_names() or [],
                })
            elif self.path == "/api/settings":
                try:
                    s = load_settings(state.settings_path())
                    self._send_json(200, {
                        "endpoint": s.get("endpoint", ""),
                        "model": s.get("model", ""),
                        "has_key": bool(s.get("api_key")),
                        "presets": PRESETS,
                    })
                except OrchestratorError as e:
                    self._send_json(200, {"endpoint": "", "model": "",
                                          "has_key": False,
                                          "presets": PRESETS,
                                          "error": str(e)})
            elif self.path.startswith("/model.glb"):
                try:
                    session = Session(state.session_path)
                except (json.JSONDecodeError, ValidationError,
                        OrchestratorError) as e:
                    self._send(500, f"error: {e}".encode(), "text/plain")
                    return
                if session.tree is None:
                    self._send(404, b"no model", "text/plain")
                    return
                try:
                    if not state.built:
                        state.result = build(session.tree, state.workdir,
                                             parts_dir=state.parts_dir)
                        state.built = True
                    glb = final_glb(session.tree, state.result)
                    self._send(200, glb.read_bytes(), "model/gltf-binary")
                except (OpTreeError, OrchestratorError) as e:
                    self._send(500, f"error: {e}".encode(), "text/plain")
            elif self.path == "/api/parts":
                if not state.parts_dir:
                    self._send_json(200, {"parts": []})
                    return
                try:
                    idx = PartsIndex.load(state.parts_dir)
                    self._send_json(200, {
                        "parts": [idx.metadata(n) for n in idx.names()]})
                except OpTreeError as e:
                    self._send_json(200, {"parts": [], "error": str(e)})
            elif self.path.startswith("/part.glb"):
                query = urllib.parse.urlparse(self.path).query
                name = urllib.parse.parse_qs(query).get("name", [None])[0]
                try:
                    if not name or not state.parts_dir:
                        raise OpTreeError("missing part name or parts dir")
                    glb = PartsIndex.load(state.parts_dir).resolve(name)
                    self._send(200, glb.read_bytes(), "model/gltf-binary")
                except OpTreeError as e:
                    self._send(404, f"error: {e}".encode(), "text/plain")
            elif self.path.startswith("/preview.png"):
                png = state.workdir / "out" / "preview.png"
                if png.exists():
                    self._send(200, png.read_bytes(), "image/png")
                else:
                    self._send(404, b"no preview", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path == "/api/settings":
                try:
                    payload = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"])))
                    current = load_settings(state.settings_path())
                    if payload.get("api_key"):
                        current["api_key"] = payload["api_key"]
                    current["endpoint"] = payload.get(
                        "endpoint", current.get("endpoint", ""))
                    current["model"] = payload.get(
                        "model", current.get("model", ""))
                    save_settings(state.settings_path(), current)
                    for k, v in current.items():
                        if v:
                            os.environ[SETTINGS_KEYS[k]] = v
                        else:
                            os.environ.pop(SETTINGS_KEYS[k], None)
                    self._send_json(200, {"ok": True})
                except (OrchestratorError, json.JSONDecodeError,
                        ValueError, TypeError, KeyError) as e:
                    self._send_json(200, {"ok": False, "error": str(e)})
                return
            if self.path == "/api/edit":
                try:
                    payload = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"])))
                    session = Session(state.session_path)
                    if session.tree is None:
                        raise OrchestratorError("no session tree to edit")
                    op = payload["op"]
                    t = session.tree
                    if op == "add_part":
                        t = add_part(t, payload["node_id"], payload["part"], payload["parent"],
                                   payload["location"], payload["rotation_deg"], payload["scale"])
                    elif op == "update_transform":
                        t = update_transform(t, payload["node_id"],
                                             location=payload.get("location"),
                                             rotation_deg=payload.get("rotation_deg"),
                                             scale=payload.get("scale"))
                    elif op == "remove_node":
                        t = remove_node(t, payload["node_id"])
                    elif op == "cut_slot":
                        t = cut_slot(t, payload["node_id"], payload["target"],
                                     payload["size"], payload["location"])
                    else:
                        raise OrchestratorError(f"unknown edit op {op!r}")
                    session.tree = t
                    session.save()
                    state.result = build(session.tree, state.workdir,
                                         parts_dir=state.parts_dir)
                    state.built = True
                    render_glb(final_glb(session.tree, state.result),
                               state.workdir / "out" / "preview.png", state.workdir)
                    tree = {"nodes": {k: v.model_dump(exclude_defaults=True)
                            for k, v in t.nodes.items()}}
                    self._send_json(200, {"ok": True, "tree": tree, "nodes": list(session.tree.nodes)})
                except (OrchestratorError, OpTreeError, json.JSONDecodeError,
                        ValidationError, ValueError, TypeError, KeyError) as e:
                    self._send_json(200, {"ok": False, "error": str(e)})
                return
            if self.path == "/api/snap":
                try:
                    payload = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"])))
                    part = payload["part"]
                    point = payload["target_point"]
                    normal = payload["target_normal"]
                    candidates = payload.get("candidates", [])
                    hit = snap_position(
                        [(tuple(c["position"]), tuple(c["normal"])) for c in candidates],
                        tuple(point), radius=payload.get("radius", 2.0))
                    if hit is None:
                        self._send_json(200, {"snapped": False})
                    else:
                        pos, n = hit
                        self._send_json(200, {
                            "snapped": True,
                            "location": list(pos),
                            "rotation_deg": list(align_rotation_deg(tuple(normal))),
                            "snap_point": list(pos),
                        })
                except (OrchestratorError, ValueError, TypeError, KeyError) as e:
                    self._send_json(200, {"ok": False, "error": str(e)})
                return
            if self.path != "/api/apply":
                self._send(404, b"not found", "text/plain")
                return
            try:
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"])))
                instruction = payload["instruction"]
                focus = payload.get("node") or None
                session = Session(state.session_path)
                result = session.apply(state.llm_factory(), instruction,
                                       available_parts=state.part_names(),
                                       focus_node=focus)
                # Build once and keep the result cached for /model.glb.
                state.result = build(session.tree, state.workdir,
                                     parts_dir=state.parts_dir)
                state.built = True
                render_glb(final_glb(session.tree, state.result),
                           state.workdir / "out" / "preview.png",
                           state.workdir)
                self._send_json(200, {"ok": True, "rounds": result.rounds,
                                      "nodes": len(result.tree.nodes)})
            except (OrchestratorError, OpTreeError, json.JSONDecodeError,
                    ValidationError, ValueError, TypeError, KeyError) as e:
                self._send_json(200, {"ok": False, "error": str(e)})

    return ThreadingHTTPServer((host, port), Handler)


def serve(session_path, workdir, parts_dir, llm_factory,
          host="127.0.0.1", port=8787,
          settings_path: Path | None = None) -> None:
    server = make_server(session_path, workdir, parts_dir, llm_factory,
                         host, port, settings_path=settings_path)
    print(f"serving on http://{host}:{server.server_address[1]}")
    server.serve_forever()
