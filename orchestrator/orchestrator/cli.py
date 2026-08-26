import argparse
import json
import sys
from pathlib import Path

from optree.engine import build
from optree.errors import OpTreeError
from optree.parts import PartsIndex
from pydantic import ValidationError

from orchestrator.check import self_check
from orchestrator.config import load_env
from orchestrator.errors import OrchestratorError
from orchestrator.llm import LLMClient, MoonshotClient
from orchestrator.pipeline import build_and_render
from orchestrator.server import serve as serve_ui
from orchestrator.session import Session


def main(argv: list[str] | None = None, llm: LLMClient | None = None) -> int:
    load_env()  # picks up MOONSHOT_* from ./.env if present
    parser = argparse.ArgumentParser(prog="orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--session", type=Path, default=Path(".exco/session.json"))
    common.add_argument("--parts", type=Path, default=Path("parts"))
    common.add_argument("--workdir", type=Path, default=Path(".exco/build"))

    a = sub.add_parser("apply", parents=[common], help="apply a natural-language instruction")
    a.add_argument("instruction")
    a.add_argument("--check", action="store_true", help="vision self-check after apply")
    sub.add_parser("build", parents=[common], help="build the current tree to fbx")
    sub.add_parser("show", parents=[common], help="print the current tree")
    sub.add_parser("preview", parents=[common], help="build and render a preview png")
    s = sub.add_parser("serve", parents=[common], help="start the local web ui")
    s.add_argument("--port", type=int, default=8787)

    args = parser.parse_args(argv)

    try:
        session = Session(args.session)
        if args.cmd == "apply":
            client = llm if llm is not None else MoonshotClient()
            parts = None
            if args.parts.exists():
                index = PartsIndex.load(args.parts)
                parts = [index.describe(n) for n in index.names()]
            result = session.apply(client, args.instruction, available_parts=parts)
            print(f"applied in rounds={result.rounds}, nodes={len(result.tree.nodes)}")
            if args.check:
                print(self_check(
                    session, client, args.instruction, args.workdir,
                    args.parts if args.parts.exists() else None,
                    available_parts=parts))
        elif args.cmd == "build":
            if session.tree is None:
                print(f"error: no session tree at {args.session}", file=sys.stderr)
                return 1
            parts_dir = args.parts if args.parts.exists() else None
            for p in build(session.tree, args.workdir, parts_dir=parts_dir).exports:
                print(p)
        elif args.cmd == "show":
            if session.tree is None:
                print(f"error: no session tree at {args.session}", file=sys.stderr)
                return 1
            print(json.dumps(
                {"nodes": {k: v.model_dump(exclude_defaults=True)
                           for k, v in session.tree.nodes.items()}},
                indent=2,
            ))
        elif args.cmd == "preview":
            png = build_and_render(
                session, args.workdir,
                args.parts if args.parts.exists() else None)
            print(png)
        elif args.cmd == "serve":
            serve_ui(args.session, args.workdir,
                     args.parts if args.parts.exists() else None,
                     llm_factory=MoonshotClient, port=args.port)
    except (OrchestratorError, OpTreeError, json.JSONDecodeError, ValidationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
