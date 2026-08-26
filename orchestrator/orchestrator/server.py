"""Local web UI: stdlib http server + three.js frontend. Single user, localhost."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from optree.errors import OpTreeError

from orchestrator.errors import OrchestratorError
from orchestrator.pipeline import build_and_render, final_glb
from orchestrator.session import Session

STATIC_DIR = Path(__file__).parent / "static"


class _State:
    def __init__(self, session_path: Path, workdir: Path,
                 parts_dir: Path | None, llm_factory):
        self.session_path = Path(session_path)
        self.workdir = Path(workdir)
        self.parts_dir = parts_dir
        self.llm_factory = llm_factory
        self.built = False  # whether model.glb/preview are up to date

    def part_names(self) -> list[str] | None:
        if self.parts_dir and Path(self.parts_dir).exists():
            from optree.parts import PartsIndex
            idx = PartsIndex.load(self.parts_dir)
            return [idx.describe(n) for n in idx.names()]
        return None


def make_server(session_path, workdir, parts_dir, llm_factory,
                host="127.0.0.1", port=8787) -> ThreadingHTTPServer:
    state = _State(session_path, workdir, parts_dir, llm_factory)

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
                session = Session(state.session_path)
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
            elif self.path.startswith("/model.glb"):
                session = Session(state.session_path)
                if session.tree is None:
                    self._send(404, b"no model", "text/plain")
                    return
                try:
                    if not state.built:
                        from optree.engine import build
                        state.result = build(session.tree, state.workdir,
                                             parts_dir=state.parts_dir)
                        state.built = True
                    glb = final_glb(session.tree, state.result)
                    self._send(200, glb.read_bytes(), "model/gltf-binary")
                except (OpTreeError, OrchestratorError) as e:
                    self._send(500, f"error: {e}".encode(), "text/plain")
            elif self.path.startswith("/preview.png"):
                png = state.workdir / "out" / "preview.png"
                if png.exists():
                    self._send(200, png.read_bytes(), "image/png")
                else:
                    self._send(404, b"no preview", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path != "/api/apply":
                self._send(404, b"not found", "text/plain")
                return
            try:
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"])))
                instruction = payload["instruction"]
                session = Session(state.session_path)
                result = session.apply(state.llm_factory(), instruction,
                                       available_parts=state.part_names())
                build_and_render(session, state.workdir, state.parts_dir)
                state.built = False
                self._send_json(200, {"ok": True, "rounds": result.rounds,
                                      "nodes": len(result.tree.nodes)})
            except (OrchestratorError, OpTreeError, json.JSONDecodeError,
                    KeyError) as e:
                self._send_json(200, {"ok": False, "error": str(e)})

    return ThreadingHTTPServer((host, port), Handler)


def serve(session_path, workdir, parts_dir, llm_factory,
          host="127.0.0.1", port=8787) -> None:
    server = make_server(session_path, workdir, parts_dir, llm_factory,
                         host, port)
    print(f"serving on http://{host}:{server.server_address[1]}")
    server.serve_forever()
