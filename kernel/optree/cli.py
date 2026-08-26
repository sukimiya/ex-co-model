import argparse
import sys
from pathlib import Path

from optree.engine import build
from optree.errors import OpTreeError
from optree.schema import load_optree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="optree")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build an optree json into fbx")
    b.add_argument("tree", type=Path)
    b.add_argument("--workdir", type=Path, default=Path(".optree"))
    args = parser.parse_args(argv)

    if args.cmd == "build":
        try:
            tree = load_optree(args.tree)
        except Exception as e:
            print(f"error: invalid optree: {e}", file=sys.stderr)
            return 1
        try:
            result = build(tree, args.workdir)
        except OpTreeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for p in result.exports:
            print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
