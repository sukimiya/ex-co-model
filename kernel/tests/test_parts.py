import json

import pytest

from optree.errors import OpTreeError
from optree.parts import PartsIndex


@pytest.fixture
def parts_dir(tmp_path):
    (tmp_path / "turret.glb").write_bytes(b"glb-turret")
    (tmp_path / "nozzle.glb").write_bytes(b"glb-nozzle")
    (tmp_path / "index.json").write_text(json.dumps({
        "parts": {
            "pdc_turret": {"file": "turret.glb", "description": "point defense turret"},
            "engine_nozzle": {"file": "nozzle.glb", "description": "engine nozzle"},
        }
    }), encoding="utf-8")
    return tmp_path


def test_load_and_resolve(parts_dir):
    idx = PartsIndex.load(parts_dir)
    assert idx.resolve("pdc_turret") == parts_dir / "turret.glb"
    assert sorted(idx.names()) == ["engine_nozzle", "pdc_turret"]


def test_resolve_unknown_part_raises(parts_dir):
    with pytest.raises(OpTreeError, match="unknown part"):
        PartsIndex.load(parts_dir).resolve("railgun")


def test_missing_index_raises(tmp_path):
    with pytest.raises(OpTreeError, match="index.json"):
        PartsIndex.load(tmp_path)


def test_missing_part_file_raises(tmp_path):
    (tmp_path / "index.json").write_text(json.dumps({
        "parts": {"ghost": {"file": "ghost.glb", "description": "missing file"}}
    }), encoding="utf-8")
    with pytest.raises(OpTreeError, match="ghost.glb"):
        PartsIndex.load(tmp_path)


def test_content_hash_changes_with_file(parts_dir):
    idx = PartsIndex.load(parts_dir)
    h1 = idx.content_hash("pdc_turret")
    (parts_dir / "turret.glb").write_bytes(b"glb-turret-v2")
    assert idx.content_hash("pdc_turret") != h1
