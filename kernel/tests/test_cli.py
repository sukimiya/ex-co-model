import json

from optree.cli import main
from tests.conftest import requires_blender


def test_cli_rejects_invalid_tree(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"nodes": {"a": {"op": "explode"}}}), encoding="utf-8")
    assert main(["build", str(bad)]) == 1
    assert "error" in capsys.readouterr().err


def test_cli_rejects_missing_file(tmp_path, capsys):
    assert main(["build", str(tmp_path / "nope.json")]) == 1


@requires_blender
def test_cli_builds_example(tmp_path, capsys):
    example = __import__("pathlib").Path(__file__).parent.parent / "examples" / "razorback_demo.json"
    assert main(["build", str(example), "--workdir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "razorback.fbx" in out
    assert (tmp_path / "out" / "razorback.fbx").exists()
