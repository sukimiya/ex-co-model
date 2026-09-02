# Kitbash Editor (Sub-project 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let players assemble ships by hand in the 3D viewport — drag parts in, move/rotate/scale/delete, snap them onto sockets and hull faces, and cut slots, with every manual action written into the OpTree so the AI and the manual editor share one source of truth.

**Architecture:** Manual edits never touch the LLM: the frontend posts structured edit ops to a new `POST /api/edit` endpoint which mutates the OpTree through the same pydantic+DAG validation the LLM path uses, then rebuilds incrementally. Snapping (socket-to-socket and face-snapping) is a server-side pure function so it is unit-testable; the frontend only sends raw geometry (hit point/normal) and receives back position+rotation to apply. All mutations reuse the existing OpTree validation, session persistence, and incremental build.

**Spec:** `docs/superpowers/specs/2026-09-02-kitbash-editor-design.md`

**Tech Stack:** Python 3.14, pydantic v2, pytest, stdlib http server, three.js (TransformControls via CDN).

## Global Constraints

- Repo root: `/Users/breannalinlin/code/Github/ex-co-model`. Work directly on `main`.
- Test commands: `cd kernel && .venv/bin/pytest` and `cd orchestrator && ../kernel/.venv/bin/pytest` (shared venv at `kernel/.venv`). No new third-party runtime dependencies.
- Code identifiers/comments/commit messages in English (conventional commits). UI strings in Chinese.
- Commit at the end of every task; push after the final task.
- Manual editing must never touch the LLM; every edit validates through the same OpTree validation as LLM output.

---

### Task 1: structured snap points in the parts library

**Files:**
- Modify: `parts/index.json` (add `snap_points` to all three parts)
- Modify: `kernel/optree/parts.py` (validate + expose snap points)
- Test: `kernel/tests/test_parts.py`

**Interfaces:**
- Consumes: `PartsIndex` (existing), `parts/index.json`.
- Produces:
  - index.json entry format gains optional `snap_points: [{"position": [x,y,z], "normal": [x,y,z], ...}]` — local part coordinates.
  - `PartsIndex.snap_points(name: str) -> list[dict]` — returns `[]` when absent; each entry has `position: [x,y,z]` and `normal: [x,y,z]` (unit-ish, world-frame of the part as authored).

- [ ] **Step 1: Write the failing tests**

Append to `kernel/tests/test_parts.py` (read it first; follow its fixture for locating the real parts dir):

```python
def test_snap_points_available():
    index = PartsIndex.load(PARTS_DIR)  # match the file's existing fixture for the real parts dir
    for name in index.names():
        pts = index.snap_points(name)
        assert pts, f"part {name} must define at least one snap point"
        for p in pts:
            assert "position" in p and "normal" in p
            assert len(p["position"]) == 3 and len(p["normal"]) == 3


def test_snap_points_parsed_from_entry():
    idx = PartsIndex.load(PARTS_DIR)
    p0 = idx.snap_points("pdc_turret")[0]
    assert set(p0) == {"position", "normal"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd kernel && .venv/bin/pytest tests/test_parts.py -k snap_points -v`
Expected: FAIL (`AttributeError: 'PartsIndex' object has no attribute 'snap_points'`)

- [ ] **Step 3: Implement PartsIndex.snap_points**

In `kernel/optree/parts.py`, after `describe`:

```python
    def snap_points(self, name: str) -> list[dict]:
        """Socket points in part-local coordinates: [{"position": [x,y,z], "normal": [x,y,z]}]."""
        if name not in self._parts:
            raise OpTreeError(
                f"unknown part {name!r}; available: {sorted(self._parts)}"
            )
        return list(self._parts[name].get("snap_points", []))
```

Also extend the `load()` validation: when an entry has `snap_points`, assert it is a list of dicts each with 3-number `position` and `normal` lists (raise OpTreeError otherwise):

```python
            pts = entry.get("snap_points")
            if pts is not None:
                if not isinstance(pts, list):
                    raise OpTreeError(f"invalid snap_points for part {name!r}")
                for pt in pts:
                    ok = (isinstance(pt, dict)
                          and isinstance(pt.get("position"), list) and len(pt["position"]) == 3
                          and isinstance(pt.get("normal"), list) and len(pt["normal"]) == 3)
                    if not ok:
                        raise OpTreeError(f"invalid snap point in part {name!r}")
```

- [ ] **Step 4: Add real snap points to parts/index.json**

Read `parts/build_parts.py` (the generator) to get exact geometry, then add to each entry a `snap_points` list with at least the mount socket. For the turret (origin at base center, mounts downward): `[{"position": [0, 0, 0], "normal": [0, 0, -1]}]`. Engine nozzle and antenna analogous, matching their authored origins — derive values from `build_parts.py`, do not guess.

- [ ] **Step 5: Run all kernel tests**

Run: `cd kernel && .venv/bin/pytest`
Expected: all PASS (64 existing + 2 new).

- [ ] **Step 6: Commit**

```bash
git add kernel/optree/parts.py kernel/tests/test_parts.py parts/index.json
git commit -m "feat(parts): structured snap points with validation"
```

---

### Task 2: `edit.py` — deterministic tree mutations

**Files:**
- Create: `orchestrator/orchestrator/edit.py`
- Test: `orchestrator/tests/test_edit.py`

**Interfaces:**
- Consumes: `optree.schema.OpTree`, `optree.graph.topo_order`, `optree.errors.OpTreeError`.
- Produces (each raises `OrchestratorError` on bad input and returns a NEW validated OpTree; input tree never mutated):
  - `add_part(tree: OpTree, node_id: str, part: str, parent: str, location, rotation_deg, scale) -> OpTree`
  - `update_transform(tree, node_id, *, location=None, rotation_deg=None, scale=None) -> OpTree`
  - `remove_node(tree, node_id) -> OpTree`
  - `cut_slot(tree, node_id, target, size: list[float], location) -> OpTree` (adds a box cutter primitive named `{node_id}_cutter` + boolean_subtract node named `node_id`)

- [ ] **Step 1: Write the failing tests**

`orchestrator/tests/test_edit.py`:

```python
import pytest

from optree.schema import OpTree

from orchestrator.edit import add_part, cut_slot, remove_node, update_transform
from orchestrator.errors import OrchestratorError


def make_tree():
    return OpTree.model_validate({"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "gun": {"op": "attach_part", "inputs": ["hull"],
                "params": {"part": "pdc_turret", "location": [5, 0, 3]}},
        "out": {"op": "export_fbx", "inputs": ["gun"]},
    }})


def test_add_part():
    t = add_part(make_tree(), "ant", "comm_antenna", "hull", [0, 0, 3], [0, 0, 0], 1.0)
    assert t.nodes["ant"].op == "attach_part"
    assert t.nodes["ant"].inputs == ["hull"]
    assert t.nodes["ant"].params.part == "comm_antenna"


def test_add_part_unknown_parent_rejected():
    with pytest.raises(OrchestratorError):
        add_part(make_tree(), "x", "comm_antenna", "nope", [0, 0, 0], [0, 0, 0], 1.0)


def test_update_transform():
    t = update_transform(make_tree(), "gun", location=[9, 1, 3])
    assert tuple(t.nodes["gun"].params.location) == (9, 1, 3)
    assert t.nodes["gun"].params.scale == 1.0  # untouched


def test_update_transform_rejects_non_part():
    with pytest.raises(OrchestratorError):
        update_transform(make_tree(), "hull", location=[0, 0, 0])


def test_remove_node_rewires_child():
    t = remove_node(make_tree(), "gun")
    assert "gun" not in t.nodes
    assert t.nodes["out"].inputs == ["hull"]


def test_remove_leaf_errors_on_unknown():
    with pytest.raises(OrchestratorError):
        remove_node(make_tree(), "ghost")


def test_cut_slot():
    t = cut_slot(make_tree(), "slot1", "hull", [4, 2, 2], [10, 0, 3])
    assert t.nodes["slot1_cutter"].op == "primitive"
    assert t.nodes["slot1"].op == "boolean_subtract"
    assert t.nodes["slot1"].inputs == ["hull", "slot1_cutter"]


def test_cut_slot_duplicate_name_rejected():
    with pytest.raises(OrchestratorError):
        cut_slot(make_tree(), "hull", "hull", [1, 1, 1], [0, 0, 0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_edit.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.edit`)

- [ ] **Step 3: Implement edit.py**

```python
"""Deterministic OpTree mutations for manual (non-LLM) editing."""

from optree.graph import topo_order
from optree.schema import OpTree

from orchestrator.errors import OrchestratorError


def _validated(nodes: dict) -> OpTree:
    tree = OpTree.model_validate({"nodes": nodes})
    topo_order(tree)  # cycle check, same gate as the LLM path
    return tree


def _dump(tree: OpTree) -> dict:
    return {k: v.model_dump() for k, v in tree.nodes.items()}


def _node_or_raise(tree: OpTree, node_id: str):
    if node_id not in tree.nodes:
        raise OrchestratorError(f"unknown node {node_id!r}")
    return tree.nodes[node_id]


def add_part(tree: OpTree, node_id: str, part: str, parent: str,
             location, rotation_deg, scale) -> OpTree:
    nodes = _dump(tree)
    if node_id in nodes:
        raise OrchestratorError(f"node {node_id!r} already exists")
    _node_or_raise(tree, parent)
    nodes[node_id] = {
        "op": "attach_part", "inputs": [parent],
        "params": {"part": part, "location": list(location),
                   "rotation_deg": list(rotation_deg), "scale": scale},
    }
    return _validated(nodes)


def update_transform(tree: OpTree, node_id: str, *, location=None,
                     rotation_deg=None, scale=None) -> OpTree:
    node = _node_or_raise(tree, node_id)
    if node.op != "attach_part":
        raise OrchestratorError(
            f"node {node_id!r} is {node.op}; only attach_part can be transformed")
    nodes = _dump(tree)
    p = nodes[node_id]["params"]
    if location is not None:
        p["location"] = list(location)
    if rotation_deg is not None:
        p["rotation_deg"] = list(rotation_deg)
    if scale is not None:
        p["scale"] = scale
    return _validated(nodes)


def remove_node(tree: OpTree, node_id: str) -> OpTree:
    node = _node_or_raise(tree, node_id)
    nodes = _dump(tree)
    del nodes[node_id]
    fallback = node.inputs[0] if node.inputs else None
    for child in nodes.values():
        child["inputs"] = [
            (fallback if ref == node_id else ref) for ref in child["inputs"]
        ]
        if fallback is None and node_id in [r for r in child["inputs"]]:
            raise OrchestratorError(
                f"cannot remove {node_id!r}: still referenced and has no input")
    return _validated(nodes)


def cut_slot(tree: OpTree, node_id: str, target: str,
             size, location) -> OpTree:
    nodes = _dump(tree)
    if node_id in nodes or f"{node_id}_cutter" in nodes:
        raise OrchestratorError(f"node {node_id!r} already exists")
    _node_or_raise(tree, target)
    nodes[f"{node_id}_cutter"] = {
        "op": "primitive",
        "params": {"type": "box", "size": list(size), "location": list(location)},
    }
    nodes[node_id] = {
        "op": "boolean_subtract", "inputs": [target, f"{node_id}_cutter"],
    }
    return _validated(nodes)
```

- [ ] **Step 4: Run all orchestrator tests**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest`
Expected: all PASS (83 existing + 8 new).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator/edit.py orchestrator/tests/test_edit.py
git commit -m "feat(orchestrator): deterministic optree edit operations"
```

---

### Task 3: `snap.py` — server-side snapping math

**Files:**
- Create: `orchestrator/orchestrator/snap.py`
- Test: `orchestrator/tests/test_snap.py`

**Interfaces:**
- Consumes: nothing (pure math).
- Produces:
  - `align_rotation_deg(normal: tuple[float, float, float], mount_axis: tuple[float, float, float] = (0, 0, 1)) -> tuple[float, float, float]` — Euler XYZ degrees (Blender convention) rotating `mount_axis` onto `normal`, zero roll.
  - `snap_position(candidates: list[tuple[list[float], list[float]]], point: tuple[float, float, float], radius: float) -> tuple[list[float], list[float]] | None` — `candidates` are `(position, normal)` pairs in world space; returns the closest within `radius`, else None.

- [ ] **Step 1: Write the failing tests**

`orchestrator/tests/test_snap.py`:

```python
import math

from orchestrator.snap import align_rotation_deg, snap_position


def _apply_euler_xyz(v, deg):
    """Rotate v by Blender-XYZ euler (degrees) — pure-python reference."""
    rx, ry, rz = (math.radians(a) for a in deg)
    def rot_x(p):
        x, y, z = p
        c, s = math.cos(rx), math.sin(rx)
        return (x, y * c - z * s, y * s + z * c)
    def rot_y(p):
        x, y, z = p
        c, s = math.cos(ry), math.sin(ry)
        return (x * c + z * s, y, -x * s + z * c)
    def rot_z(p):
        x, y, z = p
        c, s = math.cos(rz), math.sin(rz)
        return (x * c - y * s, x * s + y * c, z)
    return rot_z(rot_y(rot_x(v)))


def test_align_rotation_identity():
    assert align_rotation_deg((0, 0, 1)) == (0.0, 0.0, 0.0)


def test_align_rotation_to_plus_x():
    r = align_rotation_deg((1, 0, 0))
    out = _apply_euler_xyz((0, 0, 1), r)
    assert all(abs(a - b) < 1e-6 for a, b in zip(out, (1, 0, 0)))


def test_align_rotation_arbitrary_normal():
    n = (0.267, 0.535, 0.802)
    r = align_rotation_deg(n)
    out = _apply_euler_xyz((0, 0, 1), r)
    got = (out[0] / 1, out[1], out[2])
    exp = (n[0] / math.sqrt(sum(c * c for c in n)),
           n[1] / math.sqrt(sum(c * c for c in n)),
           n[2] / math.sqrt(sum(c * c for c in n)))
    assert all(abs(a - b) < 1e-4 for a, b in zip(got, exp))


def test_snap_position_picks_closest_within_radius():
    candidates = [([10, 0, 0], [0, 0, 1]), ([2, 0, 0], [0, 1, 0])]
    hit = snap_position(candidates, (2.4, 0.1, 0), radius=1.0)
    assert hit == ([2, 0, 0], [0, 1, 0])


def test_snap_position_none_outside_radius():
    assert snap_position([([10, 0, 0], [0, 0, 1])], (0, 0, 0), 1.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_snap.py -v`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement snap.py**

```python
"""Pure snapping math for the kitbash editor (server-side, unit-testable)."""

import math


def _unit(v):
    length = math.sqrt(sum(c * c for c in v))
    if length < 1e-12:
        raise ValueError("zero-length vector")
    return tuple(c / length for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def align_rotation_deg(normal, mount_axis=(0.0, 0.0, 1.0)):
    """Euler XYZ degrees (Blender order) rotating mount_axis onto normal."""
    a = _unit(mount_axis)
    n = _unit(normal)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, n))))
    if dot > 1 - 1e-9:
        return (0.0, 0.0, 0.0)
    if dot < -1 + 1e-9:  # opposite: 180° about any perpendicular axis
        ref = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
        axis = _unit(_cross(a, ref))
        angle = math.pi
    else:
        axis = _unit(_cross(a, n))
        angle = math.acos(dot)
    # axis-angle -> quaternion -> Euler XYZ (Blender order)
    s = math.sin(angle / 2)
    qx, qy, qz = (axis[i] * s for i in range(3))
    qw = math.cos(angle / 2)
    # rotation matrix from quaternion
    r00 = 1 - 2 * (qy * qy + qz * qz); r01 = 2 * (qx * qy - qz * qw); r02 = 2 * (qx * qz + qy * qw)
    r10 = 2 * (qx * qy + qz * qw);     r11 = 1 - 2 * (qx * qx + qz * qz); r12 = 2 * (qy * qz - qx * qw)
    r20 = 2 * (qx * qz - qy * qw);     r21 = 2 * (qy * qz + qx * qw);     r22 = 1 - 2 * (qx * qx + qy * qy)
    # R = Rz @ Ry @ Rx  (Blender XYZ)
    ry = math.asin(max(-1.0, min(1.0, r02)))
    if abs(r02) < 1 - 1e-9:
        rx = math.atan2(-r12, r22)
        rz = math.atan2(-r01, r00)
    else:  # gimbal lock
        rx = math.atan2(r21, r11)
        rz = 0.0
    return tuple(round(math.degrees(a), 6) for a in (rx, ry, rz))


def snap_position(candidates, point, radius):
    """Closest (position, normal) candidate within radius of point, else None."""
    best = None
    best_d2 = radius * radius
    for pos, normal in candidates:
        d2 = sum((p - q) ** 2 for p, q in zip(pos, point))
        if d2 <= best_d2:
            best_d2 = d2
            best = (pos, normal)
    return best
```

- [ ] **Step 4: Run tests**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_snap.py -v`
Expected: 5 PASS. (The `_apply_euler_xyz` reference uses R = Rz@Ry@Rx; if a test fails by sign/transposition, the matrix-to-euler block is the suspect — fix the implementation, never the property assertions.)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator/snap.py orchestrator/tests/test_snap.py
git commit -m "feat(orchestrator): pure snapping math for the kitbash editor"
```

---

### Task 4: `/api/edit` and `/api/snap` endpoints

**Files:**
- Modify: `orchestrator/orchestrator/server.py` (two POST routes + part GLB serving)
- Modify: `orchestrator/orchestrator/session.py` (add `save()`)
- Test: `orchestrator/tests/test_server.py` (extend), `orchestrator/tests/test_edit_api.py` (new)

**Interfaces:**
- Consumes: `edit.py` functions (Task 2), `snap.py` (Task 3), `PartsIndex.snap_points` (Task 1), `Session` (existing).
- Produces:
  - `POST /api/edit` body `{"op": "add_part"|"update_transform"|"remove_node"|"cut_slot", ...op-specific fields...}` → applies the matching `edit.py` function to the session tree, saves, rebuilds, re-renders preview, responds `{"ok": true, "tree": {...}}` or `{"ok": false, "error": ...}`.
  - `POST /api/snap` body `{"part": str, "target_point": [x,y,z], "target_normal": [x,y,z], "candidates": [[x,y,z], ...]}` → `{"location": [x,y,z], "rotation_deg": [x,y,z], "snapped": true|false, "snap_point": [x,y,z]|null}`.
  - `GET /api/parts` → `{"parts": [{"name", "description", "approx_size_m", "snap_points"}]}`.
  - `GET /part.glb?name=<part>` → the part's GLB bytes (for the palette preview).
  - `Session.save() -> None` — the atomic write currently inline in `Session.apply`, extracted so both apply and /api/edit reuse it.

- [ ] **Step 1: Write the failing tests**

`orchestrator/tests/test_edit_api.py` (boot a real server exactly like test_server.py does; reuse its fixture pattern with a tmp session file):

```python
import json


def _tree(session_path):
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps({"nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [40, 8, 6]}},
        "out": {"op": "export_fbx", "inputs": ["hull"]},
    }}), encoding="utf-8")


def test_api_edit_add_part(server):  # adapt fixture name to test_server.py's
    ...
```

Write tests covering: `add_part` via HTTP (response `ok: true`, tree contains the new node with `inputs == ["hull"]`), `update_transform` (location updated), `remove_node` (node gone, `out` rewired to `hull`), `cut_slot` (cutter + boolean nodes present), an invalid op (`{"op": "explode"}` → `ok: false`), and `/api/snap` returning `snapped: true` with `snap_point` when a candidate is within radius. Use the same fake-llm/mocking approach as the existing server tests; no Blender build should run — monkeypatch `build`/`render_glb` the way the existing server tests do.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_edit_api.py -v`
Expected: FAIL (404s / missing routes)

- [ ] **Step 3: Implement `Session.save()`**

In `session.py`, extract the atomic-write block from `apply` into:

```python
    def save(self) -> None:
        """Atomically persist the current tree (same format apply uses)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"nodes": {k: v.model_dump(exclude_defaults=True)
                           for k, v in self.tree.nodes.items()}},
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
```

and make `apply` call `self.save()` after setting `self.tree = result.tree` (replacing its inline block).

- [ ] **Step 4: Implement the routes**

In `server.py` `do_POST`, before the `/api/apply` guard add `/api/edit`:

```python
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
                            for k, v in t.nodes.items()}
                    self._send_json(200, {"ok": True, "tree": tree, "nodes": list(session.tree.nodes)})
                except (OrchestratorError, OpTreeError, json.JSONDecodeError,
                        ValidationError, ValueError, TypeError, KeyError) as e:
                    self._send_json(200, {"ok": False, "error": str(e)})
                return
```

and `/api/snap`:

```python
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
```

and in `do_GET` add `/api/parts` (returning `snap_points` per part from `PartsIndex`) and `/part.glb?name=...` serving `index.resolve(name)` bytes as `model/gltf-binary`.

- [ ] **Step 5: Run all orchestrator tests**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/orchestrator/server.py orchestrator/orchestrator/session.py orchestrator/tests/
git commit -m "feat(server): /api/edit, /api/snap, and part serving for the kitbash editor"
```

---

### Task 5: frontend — parts panel, transform gizmo, snapping, cut tool

**Files:**
- Modify: `orchestrator/orchestrator/static/index.html` (major: editor interactions)

**Interfaces:**
- Consumes: `/api/parts`, `/part.glb?name=...`, `/api/edit`, `/api/snap`, `/model.glb` (existing), `/api/state` (existing).
- Produces: the interactive editor described in spec §5.

- [ ] **Step 1: Parts panel**

Add a left column (`#palette`) listing parts from `/api/parts`. Each item is draggable-free HTML: clicking a part "picks it up" (attach a ghost preview to the cursor in the viewport). Implement:

```js
async function loadPalette() {
  const r = await (await fetch("/api/parts")).json();
  const el = document.getElementById("palette");
  el.innerHTML = "";
  for (const p of r.parts) {
    const d = document.createElement("div");
    d.className = "part";
    d.textContent = p.name;
    d.onclick = () => startPlacement(p.name);
    el.appendChild(d);
  }
}
```

(Full CSS/DOM details are the implementer's to write, following the existing dark-theme style; list parts, click → placement mode.)

- [ ] **Step 2: Selection + transform gizmo**

Add `TransformControls` from `three/addons/controls/TransformControls.js`. Raycast on pointerdown against the loaded model's meshes; map the hit object back to its OpTree node — for MVP, attach_part nodes appear as separate top-level objects in the GLB scene (the Empty-rig import creates named objects from Blender; verify in acceptance). On mouseup after a gizmo drag, convert the object's three.js (Y-up) world transform to Blender coordinates `(x, y, z)_blender = (x, z, -y)_three` and POST `/api/edit` `update_transform`.

- [ ] **Step 3: Snapping**

During a gizmo drag in translate mode, send the dragged object's world position + the raycast hit under the cursor to `/api/snap`; on `snapped: true`, ghost-preview the part at the returned location (semi-transparent clone) and, on mouseup, use the server's location/rotation_deg in the `update_transform`/`add_part` call. On `snapped: false`, use the raw transform.

- [ ] **Step 4: Cut tool**

A "开槽" mode button: click a face on the model → raycast gives point+normal → POST `/api/edit` `cut_slot` with a default box size `[2, 2, 2]` centered at the hit point. After the op, reload the model.

- [ ] **Step 5: Smoke + manual acceptance**

Run `kernel/.venv/bin/orchestrator serve` from repo root, open http://127.0.0.1:8787, and record for the report: parts listed, add_part via panel, snap behavior (screenshot or state dump), transform persistence in `/api/state` after a move, cut_slot changing the mesh. Verify with `curl /api/state` before/after each op.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/orchestrator/static/index.html
git commit -m "feat(ui): interactive kitbash editor with snapping and cut tool"
```

---

### Task 6: real acceptance + docs

**Files:**
- Modify: `docs/superpowers/specs/2026-08-27-desktop-app-design.md` (mark sub-project 2 delivered pieces)
- Modify: `.superpowers/sdd/progress.md` (ledger)

**Interfaces:**
- Consumes: everything above; real LLM via repo-root `.env`.
- Produces: acceptance evidence recorded in progress.md.

- [ ] **Step 1: Editor acceptance**

With `kernel/.venv/bin/orchestrator serve` running: create a hull via one text instruction, then through the UI place a pdc_turret on the hull (snap), move it, scale the antenna, cut a slot. Record `/api/state` diffs after each op in the report. Verify in Blender-independent terms that the tree changed exactly as expected and frozen nodes are untouched.

- [ ] **Step 2: Manual/AI uniformity acceptance**

Send `apply "把 pdc_turret 移到船尾"` (real LLM). Verify the LLM modifies the manually-created node (not creating a duplicate), and the tree diff touches only the expected subtree.

- [ ] **Step 3: Export + app check**

`orchestrator build` → FBX exists; `orchestrator preview` → PNG renders. View the PNG (ReadMediaFile) and describe it in the report.

- [ ] **Step 4: Docs + ledger**

Update the desktop-app spec roadmap (mark sub-project 2 delivered), append ledger entries to `.superpowers/sdd/progress.md`.

- [ ] **Step 5: Commit + push**

```bash
git add docs/ .superpowers/sdd/progress.md 2>/dev/null; git add docs/
git commit -m "docs: record kitbash editor acceptance"
git push
```

---

## Self-Review Notes

- Spec coverage: §3 operations (Task 2+4+5), §4 snapping (Task 1+3+4+5), §5 UI (Task 5), §6 errors (Task 4), §7 tests (each task), §9 acceptance (Task 6). AI 演算补形 correctly absent.
- Placeholder scan: Task 5's frontend is necessarily less code-complete than the others (three.js interaction code is large); its steps pin exact integration points and the verification is the manual acceptance in Task 6. All Python is complete.
- Type consistency: `edit.py` function names identical in Tasks 2/4; `snap_points` accessor identical in Tasks 1/4; `align_rotation_deg`/`snap_position` identical in Tasks 3/4.
- Risk noted for Task 5: mapping three.js (Y-up) to Blender (Z-up) coordinates when sending transforms — the implementer must use `(x, y, z)_blender = (x, z, -y)_three` and verify it in the Task 6 acceptance (a moved part must land where the drag put it).
