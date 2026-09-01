"""Desktop shell: serve the orchestrator UI on localhost and show it in a
native window (pywebview). --smoke boots the server without a window."""

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ex-co-model")
    parser.add_argument("--smoke", action="store_true",
                        help="boot the server, check /api/state, exit")
    parser.add_argument("--print-blender", action="store_true",
                        help="print the resolved blender executable path, exit")
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        os.environ["EXCO_DATA_DIR"] = str(args.data_dir)

    if args.print_blender:
        from optree.blender_session import find_blender
        print(find_blender() or "BLENDER NOT FOUND")
        return 0

    from orchestrator.config import load_env
    from orchestrator.errors import OrchestratorError
    from orchestrator.paths import user_data_dir
    from orchestrator.server import make_server

    try:
        load_env()  # .env in cwd if present; settings.json under data dir
    except OrchestratorError as e:
        print(f"warning: {e}", file=sys.stderr)  # UI will surface it; keep booting
    data = user_data_dir()
    (data / "build").mkdir(parents=True, exist_ok=True)
    port = free_port()
    from orchestrator.llm import MoonshotClient
    server = make_server(
        data / "session.json",       # session file inside the data dir
        data / "build",              # workdir inside the data dir
        Path("parts") if Path("parts").exists() else None,  # dev convenience
        MoonshotClient,              # llm_factory (constructed lazily per request)
        host="127.0.0.1", port=port,
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"

    if args.smoke:
        for _ in range(50):
            try:
                with urllib.request.urlopen(url + "/api/state", timeout=2) as r:
                    json.loads(r.read())
                break
            except OSError:
                time.sleep(0.1)
        else:
            print("SMOKE FAIL: server did not respond")
            return 1
        print("SMOKE OK")
        server.shutdown()
        return 0

    import webview  # imported lazily: --smoke works without pywebview installed
    webview.create_window("ex-co-model", url, width=1400, height=900)
    webview.start()
    server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
