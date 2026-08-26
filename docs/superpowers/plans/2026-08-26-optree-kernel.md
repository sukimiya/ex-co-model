# OpTree 内核与 headless 执行器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 OpTree 的 schema 校验、DAG 解析、Blender headless 执行器与 CLI：输入一份 OpTree JSON，输出 FBX，带缓存增量重算。

**Architecture:** 纯 Python 包 `optree`。schema（pydantic 校验）→ graph（拓扑排序/受影响子树）→ keys（内容哈希缓存键）→ emit（每个节点生成 bpy 代码字符串，纯函数）→ engine（算脏节点、拼脚本、调一次 Blender 子进程）→ cli。中间产物统一为 GLB 缓存文件，最终导出 FBX。

**Tech Stack:** Python ≥3.11、pydantic v2、pytest、Blender ≥4.0（headless 子进程）。

**Spec:** `docs/superpowers/specs/2026-08-25-ex-co-model-design.md`（本计划只覆盖其中"内核 worker"与 OpTree 抽象；编排服务/LLM、UI 壳、部件库为后续计划）

## Global Constraints

- Python ≥ 3.11，pydantic ≥ 2.6，pytest ≥ 8.0
- Blender ≥ 4.0 必须在 PATH 上（`blender --version` 可查）；不修改 Blender 安装
- 本计划不调用任何 LLM/云端服务，不引入计划外依赖
- 单位一律为米；节点中间缓存格式为 GLB，最终导出 FBX
- 代码标识符与注释用英文；commit message 用英文 conventional commits
- 所有代码在 `kernel/` 子目录下，测试在 `kernel/tests/`
- TDD：先写失败测试，再写最小实现，每个 Task 结束必须 commit

---

### Task 1: 项目脚手架 + schema 校验

**Files:**
- Create: `kernel/pyproject.toml`
- Create: `kernel/optree/__init__.py`
- Create: `kernel/optree/errors.py`
- Create: `kernel/optree/schema.py`
- Test: `kernel/tests/test_schema.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces:
  - `optree.schema.OpTree`（pydantic 模型，`.nodes: dict[str, Node]`）
  - `optree.schema.Node`（discriminated union，每个节点有 `.op: str`、`.inputs: list[str]`、`.params`）
  - `optree.schema.load_optree(path: str | Path) -> OpTree`
  - `optree.errors.OpTreeError`、`optree.errors.CycleError`、`optree.errors.BlenderError`

- [ ] **Step 1: 确认 Blender 已安装**

Run: `blender --version`
Expected: 输出 `Blender 4.x.x`。若没有：`brew install --cask blender`，装完重跑确认。

- [ ] **Step 2: 创建脚手架与虚拟环境**

Create `kernel/pyproject.toml`:

```toml
[project]
name = "optree"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.6"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
optree = "optree.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["optree*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create `kernel/optree/__init__.py`（空文件）。

Run:

```bash
cd kernel && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

Expected: 安装成功，无报错。

- [ ] **Step 3: 写失败的 schema 测试**

Create `kernel/tests/test_schema.py`:

```python
import json

import pytest
from pydantic import ValidationError

from optree.schema import OpTree, load_optree


def valid_tree_dict() -> dict:
    return {
        "nodes": {
            "hull": {
                "op": "primitive",
                "params": {"type": "box", "size": [10, 3, 2]},
            },
            "hull_shaped": {
                "op": "bevel",
                "inputs": ["hull"],
                "params": {"width": 0.15, "segments": 3},
            },
            "out": {
                "op": "export_fbx",
                "inputs": ["hull_shaped"],
                "params": {"filename": "ship.fbx"},
            },
        }
    }


def test_valid_tree_parses():
    tree = OpTree.model_validate(valid_tree_dict())
    assert set(tree.nodes) == {"hull", "hull_shaped", "out"}
    assert tree.nodes["hull"].op == "primitive"
    assert tree.nodes["hull_shaped"].inputs == ["hull"]
    assert tree.nodes["hull_shaped"].params.width == 0.15


def test_unknown_input_ref_rejected():
    data = valid_tree_dict()
    data["nodes"]["hull_shaped"]["inputs"] = ["nonexistent"]
    with pytest.raises(ValidationError, match="unknown node"):
        OpTree.model_validate(data)


def test_unknown_op_rejected():
    data = valid_tree_dict()
    data["nodes"]["hull"]["op"] = "explode"
    with pytest.raises(ValidationError):
        OpTree.model_validate(data)


def test_scale_to_rejects_nonpositive_length():
    data = {
        "nodes": {
            "a": {"op": "primitive", "params": {"type": "box"}},
            "b": {"op": "scale_to", "inputs": ["a"], "params": {"length_m": 0}},
        }
    }
    with pytest.raises(ValidationError):
        OpTree.model_validate(data)


def test_load_optree_roundtrip(tmp_path):
    p = tmp_path / "tree.json"
    p.write_text(json.dumps(valid_tree_dict()), encoding="utf-8")
    tree = load_optree(p)
    assert tree.nodes["out"].params.filename == "ship.fbx"
```

- [ ] **Step 4: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_schema.py -v`
Expected: 全部 ERROR/FAIL（`ModuleNotFoundError: No module named 'optree.schema'`）

- [ ] **Step 5: 实现 errors.py 与 schema.py**

Create `kernel/optree/errors.py`:

```python
class OpTreeError(Exception):
    """Base error for all optree failures."""


class CycleError(OpTreeError):
    """The node graph contains a dependency cycle."""


class BlenderError(OpTreeError):
    """A headless Blender execution failed."""
```

Create `kernel/optree/schema.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NodeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[str] = []


class PrimitiveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["box", "cylinder"]
    size: tuple[float, float, float] = (2.0, 2.0, 2.0)  # box full extents, meters
    radius: float = 1.0          # cylinder only
    depth: float = 2.0           # cylinder only
    vertices: int = 32           # cylinder only
    location: tuple[float, float, float] = (0.0, 0.0, 0.0)


class BevelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: float = 0.1
    segments: int = 3


class ScaleToParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    length_m: float = Field(gt=0)


class ExportFbxParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = "model.fbx"


class PrimitiveNode(NodeBase):
    op: Literal["primitive"]
    params: PrimitiveParams


class BevelNode(NodeBase):
    op: Literal["bevel"]
    inputs: list[str] = Field(min_length=1, max_length=1)
    params: BevelParams = BevelParams()


class BooleanSubtractNode(NodeBase):
    op: Literal["boolean_subtract"]
    # inputs[0] = target, inputs[1] = cutter
    inputs: list[str] = Field(min_length=2, max_length=2)


class ScaleToNode(NodeBase):
    op: Literal["scale_to"]
    inputs: list[str] = Field(min_length=1, max_length=1)
    params: ScaleToParams


class ExportFbxNode(NodeBase):
    op: Literal["export_fbx"]
    inputs: list[str] = Field(min_length=1, max_length=1)
    params: ExportFbxParams = ExportFbxParams()


Node = Annotated[
    Union[PrimitiveNode, BevelNode, BooleanSubtractNode, ScaleToNode, ExportFbxNode],
    Field(discriminator="op"),
]


class OpTree(BaseModel):
    nodes: dict[str, Node]

    @model_validator(mode="after")
    def _refs_exist(self) -> "OpTree":
        for name, node in self.nodes.items():
            for ref in node.inputs:
                if ref not in self.nodes:
                    raise ValueError(f"node {name!r} references unknown node {ref!r}")
        return self


def load_optree(path: str | Path) -> OpTree:
    return OpTree.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_schema.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add kernel/
git commit -m "feat(kernel): optree schema with pydantic validation"
```

---

### Task 2: DAG 拓扑排序与受影响子树

**Files:**
- Create: `kernel/optree/graph.py`
- Test: `kernel/tests/test_graph.py`

**Interfaces:**
- Consumes: `optree.schema.OpTree`（Task 1）
- Produces:
  - `optree.graph.topo_order(tree: OpTree) -> list[str]`（有环抛 `CycleError`）
  - `optree.graph.affected_subtree(tree: OpTree, changed: set[str]) -> set[str]`（changed + 全部下游依赖者）

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/test_graph.py`:

```python
import pytest

from optree.errors import CycleError
from optree.graph import affected_subtree, topo_order
from optree.schema import OpTree


def make_tree(edges: dict[str, dict]) -> OpTree:
    return OpTree.model_validate({"nodes": edges})


def chain_tree() -> OpTree:
    return make_tree({
        "a": {"op": "primitive", "params": {"type": "box"}},
        "b": {"op": "bevel", "inputs": ["a"]},
        "c": {"op": "scale_to", "inputs": ["b"], "params": {"length_m": 28}},
    })


def test_topo_order_linear_chain():
    order = topo_order(chain_tree())
    assert order.index("a") < order.index("b") < order.index("c")


def test_topo_order_diamond():
    tree = make_tree({
        "base": {"op": "primitive", "params": {"type": "box"}},
        "cutter": {"op": "primitive", "params": {"type": "box"}},
        "cut": {"op": "boolean_subtract", "inputs": ["base", "cutter"]},
        "out": {"op": "export_fbx", "inputs": ["cut"]},
    })
    order = topo_order(tree)
    assert order.index("base") < order.index("cut")
    assert order.index("cutter") < order.index("cut")
    assert order[-1] == "out"


def test_cycle_raises():
    # schema 允许自引用环存在（引用检查只看存在性），graph 负责抓环
    tree = OpTree.model_validate({
        "nodes": {
            "a": {"op": "bevel", "inputs": ["b"]},
            "b": {"op": "bevel", "inputs": ["a"]},
        }
    })
    with pytest.raises(CycleError):
        topo_order(tree)


def test_affected_subtree_returns_downstream():
    assert affected_subtree(chain_tree(), {"a"}) == {"a", "b", "c"}
    assert affected_subtree(chain_tree(), {"b"}) == {"b", "c"}
    assert affected_subtree(chain_tree(), {"c"}) == {"c"}


def test_affected_subtree_unknown_node_raises():
    with pytest.raises(ValueError, match="unknown"):
        affected_subtree(chain_tree(), {"zzz"})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_graph.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'optree.graph'`）

- [ ] **Step 3: 实现 graph.py**

Create `kernel/optree/graph.py`:

```python
from optree.errors import CycleError
from optree.schema import OpTree


def _dependents(tree: OpTree) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {name: [] for name in tree.nodes}
    for name, node in tree.nodes.items():
        for ref in node.inputs:
            deps[ref].append(name)
    return deps


def topo_order(tree: OpTree) -> list[str]:
    """Kahn's algorithm. Raises CycleError if the graph has a cycle."""
    indegree = {name: len(node.inputs) for name, node in tree.nodes.items()}
    dependents = _dependents(tree)
    ready = sorted(n for n, d in indegree.items() if d == 0)
    order: list[str] = []
    while ready:
        name = ready.pop(0)
        order.append(name)
        for dep in dependents[name]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)
    if len(order) != len(tree.nodes):
        raise CycleError("optree contains a dependency cycle")
    return order


def affected_subtree(tree: OpTree, changed: set[str]) -> set[str]:
    """Return `changed` plus every node that (transitively) depends on them."""
    unknown = changed - set(tree.nodes)
    if unknown:
        raise ValueError(f"unknown nodes: {sorted(unknown)}")
    dependents = _dependents(tree)
    seen = set(changed)
    stack = list(changed)
    while stack:
        for dep in dependents[stack.pop()]:
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_graph.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add kernel/optree/graph.py kernel/tests/test_graph.py
git commit -m "feat(kernel): dag topo order and affected subtree"
```

---

### Task 3: 缓存键（内容哈希）

**Files:**
- Create: `kernel/optree/keys.py`
- Test: `kernel/tests/test_keys.py`

**Interfaces:**
- Consumes: `optree.schema.Node`（Task 1）
- Produces: `optree.keys.node_key(node: Node, input_keys: list[str]) -> str`（16 位十六进制哈希；同 op+params+input_keys 必同键）

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/test_keys.py`:

```python
from optree.keys import node_key
from optree.schema import OpTree


def two_trees(bevel_width: float) -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "a": {"op": "primitive", "params": {"type": "box"}},
            "b": {"op": "bevel", "inputs": ["a"], "params": {"width": bevel_width}},
        }
    })


def test_same_node_same_key():
    tree = two_trees(0.1)
    k1 = node_key(tree.nodes["a"], [])
    k2 = node_key(tree.nodes["a"], [])
    assert k1 == k2
    assert len(k1) == 16


def test_param_change_changes_key():
    k1 = node_key(two_trees(0.1).nodes["b"], ["x"])
    k2 = node_key(two_trees(0.2).nodes["b"], ["x"])
    assert k1 != k2


def test_input_key_change_changes_key():
    node = two_trees(0.1).nodes["b"]
    assert node_key(node, ["x"]) != node_key(node, ["y"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_keys.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'optree.keys'`）

- [ ] **Step 3: 实现 keys.py**

Create `kernel/optree/keys.py`:

```python
import hashlib
import json

from optree.schema import Node


def node_key(node: Node, input_keys: list[str]) -> str:
    """Content hash of op + params + input keys. Deterministic."""
    raw = node.model_dump()
    payload = {
        "op": node.op,
        "params": raw.get("params", {}),
        "inputs": input_keys,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_keys.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add kernel/optree/keys.py kernel/tests/test_keys.py
git commit -m "feat(kernel): content-hash cache keys for nodes"
```

---

### Task 4: 节点 → bpy 代码生成器（纯函数，不需要 Blender）

**Files:**
- Create: `kernel/optree/emit.py`
- Test: `kernel/tests/test_emit.py`

**Interfaces:**
- Consumes: `optree.schema` 的各 Params 类型（Task 1）
- Produces（全部为纯函数，返回 bpy Python 源码字符串，`src`/`out` 均为文件路径字符串）:
  - `optree.emit.emit_primitive(out: str, p: PrimitiveParams) -> str`
  - `optree.emit.emit_bevel(out: str, src: str, p: BevelParams) -> str`
  - `optree.emit.emit_boolean_subtract(out: str, target: str, cutter: str) -> str`
  - `optree.emit.emit_scale_to(out: str, src: str, p: ScaleToParams) -> str`
  - `optree.emit.emit_export_fbx(out: str, src: str, p: ExportFbxParams) -> str`

约定：生成的代码段假设当前 Blender 场景已清空；执行完后场景里只剩该节点的结果对象，并以 GLB（或 FBX）写入 `out`。

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/test_emit.py`:

```python
from optree.emit import (
    emit_bevel,
    emit_boolean_subtract,
    emit_export_fbx,
    emit_primitive,
    emit_scale_to,
)
from optree.schema import BevelParams, ExportFbxParams, PrimitiveParams, ScaleToParams


def test_emit_box_primitive():
    code = emit_primitive("/tmp/a.glb", PrimitiveParams(type="box", size=(10, 3, 2)))
    assert "primitive_cube_add" in code
    assert "(10, 3, 2)" in code
    assert "export_scene.gltf" in code
    assert "/tmp/a.glb" in code


def test_emit_cylinder_primitive():
    code = emit_primitive("/tmp/c.glb", PrimitiveParams(type="cylinder", radius=1.5, depth=6))
    assert "primitive_cylinder_add" in code
    assert "radius=1.5" in code
    assert "depth=6" in code


def test_emit_bevel_applies_modifier():
    code = emit_bevel("/tmp/b.glb", "/tmp/a.glb", BevelParams(width=0.15, segments=3))
    assert "import_scene.gltf" in code
    assert "/tmp/a.glb" in code
    assert "type='BEVEL'" in code
    assert "mod.width = 0.15" in code
    assert "modifier_apply" in code


def test_emit_boolean_subtract_removes_cutter():
    code = emit_boolean_subtract("/tmp/out.glb", "/tmp/t.glb", "/tmp/c.glb")
    assert code.index("/tmp/t.glb") < code.index("/tmp/c.glb")  # target imported first
    assert "operation = 'DIFFERENCE'" in code
    assert "solver = 'EXACT'" in code
    assert "bpy.data.objects.remove(cutter_obj)" in code


def test_emit_scale_to_computes_uniform_factor():
    code = emit_scale_to("/tmp/s.glb", "/tmp/a.glb", ScaleToParams(length_m=28))
    assert "28.0 / max(" in code
    assert "transform_apply" in code
    assert "/tmp/s.glb" in code


def test_emit_export_fbx():
    code = emit_export_fbx("/tmp/out/ship.fbx", "/tmp/s.glb", ExportFbxParams(filename="ship.fbx"))
    assert "export_scene.fbx" in code
    assert "/tmp/out/ship.fbx" in code
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_emit.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'optree.emit'`）

- [ ] **Step 3: 实现 emit.py**

Create `kernel/optree/emit.py`:

```python
"""Pure functions that translate OpTree nodes into Blender bpy code strings.

Each emitted segment assumes the scene starts empty and ends containing only
the node's result object(s), written to `out` as GLB (or FBX for export).
"""

from optree.schema import BevelParams, ExportFbxParams, PrimitiveParams, ScaleToParams


def _import_glb(path: str) -> str:
    return (
        f"bpy.ops.import_scene.gltf(filepath={path!r})\n"
        "imported = [o for o in bpy.context.selected_objects if o.type == 'MESH']\n"
    )


def _export_glb(path: str) -> str:
    return f"bpy.ops.export_scene.gltf(filepath={path!r}, export_format='GLB')\n"


def emit_primitive(out: str, p: PrimitiveParams) -> str:
    if p.type == "box":
        code = (
            f"bpy.ops.mesh.primitive_cube_add(size=1, location={tuple(p.location)!r})\n"
            "obj = bpy.context.active_object\n"
            f"obj.dimensions = {tuple(p.size)!r}\n"
            "bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)\n"
        )
    else:
        code = (
            f"bpy.ops.mesh.primitive_cylinder_add(vertices={p.vertices}, "
            f"radius={p.radius}, depth={p.depth}, location={tuple(p.location)!r})\n"
            "obj = bpy.context.active_object\n"
        )
    return code + _export_glb(out)


def emit_bevel(out: str, src: str, p: BevelParams) -> str:
    return (
        _import_glb(src)
        + "obj = imported[0]\n"
        + "mod = obj.modifiers.new(name='bevel', type='BEVEL')\n"
        + f"mod.width = {p.width}\n"
        + f"mod.segments = {p.segments}\n"
        + "bpy.context.view_layer.objects.active = obj\n"
        + "bpy.ops.object.modifier_apply(modifier='bevel')\n"
        + _export_glb(out)
    )


def emit_boolean_subtract(out: str, target: str, cutter: str) -> str:
    return (
        _import_glb(target)
        + "target_obj = imported[0]\n"
        + "bpy.ops.object.select_all(action='DESELECT')\n"
        + _import_glb(cutter)
        + "cutter_obj = imported[0]\n"
        + "mod = target_obj.modifiers.new(name='bool', type='BOOLEAN')\n"
        + "mod.operation = 'DIFFERENCE'\n"
        + "mod.solver = 'EXACT'\n"
        + "mod.object = cutter_obj\n"
        + "bpy.context.view_layer.objects.active = target_obj\n"
        + "bpy.ops.object.modifier_apply(modifier='bool')\n"
        + "bpy.data.objects.remove(cutter_obj)\n"
        + "bpy.ops.object.select_all(action='DESELECT')\n"
        + "target_obj.select_set(True)\n"
        + _export_glb(out)
    )


def emit_scale_to(out: str, src: str, p: ScaleToParams) -> str:
    return (
        _import_glb(src)
        + "from mathutils import Vector\n"
        + "mins = Vector((1e18, 1e18, 1e18))\n"
        + "maxs = Vector((-1e18, -1e18, -1e18))\n"
        + "for o in imported:\n"
        + "    for corner in o.bound_box:\n"
        + "        w = o.matrix_world @ Vector(corner)\n"
        + "        mins = Vector(map(min, mins, w))\n"
        + "        maxs = Vector(map(max, maxs, w))\n"
        + "dims = maxs - mins\n"
        + f"factor = {float(p.length_m)} / max(dims.x, dims.y, dims.z)\n"
        + "for o in imported:\n"
        + "    o.scale = tuple(s * factor for s in o.scale)\n"
        + "bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)\n"
        + _export_glb(out)
    )


def emit_export_fbx(out: str, src: str, p: ExportFbxParams) -> str:
    return (
        _import_glb(src)
        + f"bpy.ops.export_scene.fbx(filepath={out!r})\n"
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_emit.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add kernel/optree/emit.py kernel/tests/test_emit.py
git commit -m "feat(kernel): pure bpy code emitters for v1 node types"
```

---

### Task 5: Blender headless 子进程封装

**Files:**
- Create: `kernel/optree/blender_session.py`
- Create: `kernel/tests/conftest.py`
- Test: `kernel/tests/test_blender_session.py`

**Interfaces:**
- Consumes: `optree.errors.BlenderError`（Task 1）
- Produces:
  - `optree.blender_session.blender_available() -> bool`
  - `optree.blender_session.run_blender_script(script: str, workdir: Path) -> None`（失败抛 `BlenderError`，含 blender 输出尾部）
  - `tests/conftest.py` 提供 `requires_blender` 标记（无 blender 时 skip），后续集成测试统一使用

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/__init__.py`（空文件；让 `tests` 成为包，其他测试文件才能 `from tests.conftest import requires_blender`）。

Create `kernel/tests/conftest.py`:

```python
import shutil

import pytest

requires_blender = pytest.mark.skipif(
    shutil.which("blender") is None, reason="blender not on PATH"
)
```

Create `kernel/tests/test_blender_session.py`:

```python
import pytest

from optree.blender_session import run_blender_script
from optree.errors import BlenderError
from tests.conftest import requires_blender


@requires_blender
def test_run_script_creates_file(tmp_path):
    out = tmp_path / "hello.glb"
    script = (
        "import bpy\n"
        "bpy.ops.mesh.primitive_cube_add(size=2)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(out)!r}, export_format='GLB')\n"
    )
    run_blender_script(script, tmp_path)
    assert out.exists() and out.stat().st_size > 0


@requires_blender
def test_bad_script_raises_blender_error(tmp_path):
    with pytest.raises(BlenderError, match="blender exited"):
        run_blender_script("import bpy\nbpy.ops.nonexistent.call()\n", tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_blender_session.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'optree.blender_session'`）。注意：若 `blender` 不在 PATH，测试会被 skip，此时必须先回到 Task 1 Step 1 安装 Blender。

- [ ] **Step 3: 实现 blender_session.py**

Create `kernel/optree/blender_session.py`:

```python
import shutil
import subprocess
from pathlib import Path

from optree.errors import BlenderError


def blender_available() -> bool:
    return shutil.which("blender") is not None


def run_blender_script(script: str, workdir: Path) -> None:
    """Run a python script in one headless Blender process.

    Raises BlenderError with the tail of blender's output on failure.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    script_path = workdir / "_session.py"
    script_path.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        ["blender", "-b", "--factory-startup", "--python", str(script_path)],
        capture_output=True,
        text=True,
        cwd=workdir,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-20:])
        raise BlenderError(f"blender exited {proc.returncode}:\n{tail}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_blender_session.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add kernel/optree/blender_session.py kernel/tests/conftest.py kernel/tests/test_blender_session.py
git commit -m "feat(kernel): headless blender subprocess wrapper"
```

---

### Task 6: 构建引擎（脏节点计算 + 单次会话执行 + 增量缓存）

**Files:**
- Create: `kernel/optree/engine.py`
- Test: `kernel/tests/test_engine.py`

**Interfaces:**
- Consumes: `topo_order`（Task 2）、`node_key`（Task 3）、`optree.emit` 全部（Task 4）、`run_blender_script`（Task 5）
- Produces:
  - `optree.engine.BuildResult`（dataclass：`.glbs: dict[str, Path]`、`.exports: list[Path]`）
  - `optree.engine.build(tree: OpTree, workdir: Path) -> BuildResult`
  - 缓存布局：`workdir/cache/<node_key>.glb`、`workdir/out/<filename>.fbx`

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/test_engine.py`:

```python
from optree.engine import build
from optree.schema import OpTree
from tests.conftest import requires_blender


def ship_tree(bevel_width: float = 0.15) -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "hull": {
                "op": "primitive",
                "params": {"type": "box", "size": [10, 3, 2]},
            },
            "cutter": {
                "op": "primitive",
                "params": {"type": "box", "size": [2, 1, 0.8], "location": [0, 0, 1]},
            },
            "slotted": {
                "op": "boolean_subtract",
                "inputs": ["hull", "cutter"],
            },
            "shaped": {
                "op": "bevel",
                "inputs": ["slotted"],
                "params": {"width": bevel_width, "segments": 2},
            },
            "scaled": {
                "op": "scale_to",
                "inputs": ["shaped"],
                "params": {"length_m": 28},
            },
            "out": {
                "op": "export_fbx",
                "inputs": ["scaled"],
                "params": {"filename": "ship.fbx"},
            },
        }
    })


@requires_blender
def test_build_produces_fbx_and_cached_glbs(tmp_path):
    result = build(ship_tree(), tmp_path)
    assert result.exports == [tmp_path / "out" / "ship.fbx"]
    assert result.exports[0].exists() and result.exports[0].stat().st_size > 0
    # every geometry node has a cached glb
    assert len(result.glbs) == 5
    for p in result.glbs.values():
        assert p.exists()


@requires_blender
def test_rebuild_is_incremental(tmp_path):
    build(ship_tree(), tmp_path)
    mtimes_before = {k: p.stat().st_mtime_ns for k, p in build(ship_tree(), tmp_path).glbs.items()}

    # unchanged tree: nothing recomputed
    result2 = build(ship_tree(), tmp_path)
    for k, p in result2.glbs.items():
        assert p.stat().st_mtime_ns == mtimes_before[k]

    # change bevel width: hull/cutter/slotted cached (upstream of bevel),
    # shaped + scaled get new cache keys (downstream)
    mtimes_cached = {k: p.stat().st_mtime_ns for k, p in result2.glbs.items()}
    result3 = build(ship_tree(bevel_width=0.3), tmp_path)
    assert result3.glbs["hull"].stat().st_mtime_ns == mtimes_cached["hull"]
    assert result3.glbs["cutter"].stat().st_mtime_ns == mtimes_cached["cutter"]
    assert result3.glbs["slotted"].stat().st_mtime_ns == mtimes_cached["slotted"]
    assert result3.glbs["shaped"] != result2.glbs["shaped"]  # new cache key
    assert result3.glbs["shaped"].exists()
    assert result3.glbs["scaled"] != result2.glbs["scaled"]  # downstream also recomputed
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_engine.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'optree.engine'`）

- [ ] **Step 3: 实现 engine.py**

Create `kernel/optree/engine.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path

from optree import emit
from optree.blender_session import run_blender_script
from optree.graph import topo_order
from optree.keys import node_key
from optree.schema import OpTree

_SCENE_RESET = "bpy.ops.object.select_all(action='SELECT')\nbpy.ops.object.delete()\n"


@dataclass
class BuildResult:
    glbs: dict[str, Path] = field(default_factory=dict)
    exports: list[Path] = field(default_factory=list)


def build(tree: OpTree, workdir: Path) -> BuildResult:
    """Execute an OpTree. Cached nodes are skipped; dirty nodes run in one
    headless Blender session. Returns paths to cached glbs and exported fbx."""
    workdir = Path(workdir)
    cache = workdir / "cache"
    outdir = workdir / "out"
    cache.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    order = topo_order(tree)
    keys: dict[str, str] = {}
    glbs: dict[str, Path] = {}
    exports: dict[str, Path] = {}
    dirty: list[str] = []

    for name in order:
        node = tree.nodes[name]
        key = node_key(node, [keys[i] for i in node.inputs])
        keys[name] = key
        if node.op == "export_fbx":
            exports[name] = outdir / node.params.filename
            dirty.append(name)  # re-export every build; cheap relative to geometry
        else:
            glbs[name] = cache / f"{key}.glb"
            if not glbs[name].exists():
                dirty.append(name)

    if dirty:
        script = "import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
        for name in dirty:
            node = tree.nodes[name]
            if node.op == "primitive":
                script += emit.emit_primitive(str(glbs[name]), node.params)
            elif node.op == "bevel":
                script += emit.emit_bevel(str(glbs[name]), str(glbs[node.inputs[0]]), node.params)
            elif node.op == "boolean_subtract":
                script += emit.emit_boolean_subtract(
                    str(glbs[name]), str(glbs[node.inputs[0]]), str(glbs[node.inputs[1]])
                )
            elif node.op == "scale_to":
                script += emit.emit_scale_to(str(glbs[name]), str(glbs[node.inputs[0]]), node.params)
            elif node.op == "export_fbx":
                script += emit.emit_export_fbx(str(exports[name]), str(glbs[node.inputs[0]]), node.params)
            script += _SCENE_RESET
        run_blender_script(script, workdir)

    return BuildResult(glbs=glbs, exports=list(exports.values()))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_engine.py -v`
Expected: 2 passed

- [ ] **Step 5: 全量回归**

Run: `cd kernel && .venv/bin/pytest -v`
Expected: 全部 passed（schema 5 + graph 5 + keys 3 + emit 6 + session 2 + engine 2 = 23）

- [ ] **Step 6: Commit**

```bash
git add kernel/optree/engine.py kernel/tests/test_engine.py
git commit -m "feat(kernel): build engine with content-hash incremental cache"
```

---

### Task 7: CLI + 示例资产

**Files:**
- Create: `kernel/optree/cli.py`
- Create: `kernel/examples/razorback_demo.json`
- Test: `kernel/tests/test_cli.py`

**Interfaces:**
- Consumes: `load_optree`（Task 1）、`build`（Task 6）、`OpTreeError`（Task 1）
- Produces: `optree build <tree.json> [--workdir DIR]` 命令（pyproject 已注册 entry point，Task 1 Step 2）；stdout 逐行打印导出的 FBX 路径；失败时 stderr 打错误、退出码 1

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/test_cli.py`:

```python
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
```

Create `kernel/examples/razorback_demo.json`:

```json
{
  "nodes": {
    "hull": {
      "op": "primitive",
      "params": {"type": "box", "size": [10, 3, 2]}
    },
    "slot_cutter": {
      "op": "primitive",
      "params": {"type": "box", "size": [2, 1, 0.8], "location": [0, 0, 1]}
    },
    "slotted": {
      "op": "boolean_subtract",
      "inputs": ["hull", "slot_cutter"]
    },
    "shaped": {
      "op": "bevel",
      "inputs": ["slotted"],
      "params": {"width": 0.15, "segments": 3}
    },
    "scaled": {
      "op": "scale_to",
      "inputs": ["shaped"],
      "params": {"length_m": 28}
    },
    "out": {
      "op": "export_fbx",
      "inputs": ["scaled"],
      "params": {"filename": "razorback.fbx"}
    }
  }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_cli.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'optree.cli'`）

- [ ] **Step 3: 实现 cli.py**

Create `kernel/optree/cli.py`:

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_cli.py -v`
Expected: 3 passed

- [ ] **Step 5: 手动跑一遍示例，确认真实可用**

```bash
cd kernel && .venv/bin/optree build examples/razorback_demo.json --workdir /tmp/optree-demo
```

Expected: 输出 `/tmp/optree-demo/out/razorback.fbx`，文件非空。可用 Blender 打开验证：`blender /tmp/optree-demo/cache/*.glb` 任选一个查看（开槽的船体、总长 28 米）。

- [ ] **Step 6: Commit**

```bash
git add kernel/optree/cli.py kernel/examples/razorback_demo.json kernel/tests/test_cli.py
git commit -m "feat(kernel): optree build cli with razorback demo"
```

---

### Task 8: README + 收尾回归

**Files:**
- Create: `kernel/README.md`
- Modify: `README.md`（项目根，补一行指向 kernel）

**Interfaces:**
- Consumes: 全部前置任务
- Produces: 文档；无代码接口

- [ ] **Step 1: 写 kernel/README.md**

Create `kernel/README.md`：

````markdown
# optree kernel

OpTree（操作树）执行内核：输入一份描述建模步骤的 JSON，通过 headless Blender 执行，输出 FBX。带内容哈希缓存，修改只重算受影响子树。

## 环境

- Python ≥ 3.11
- Blender ≥ 4.0（`blender` 需在 PATH 上）

## 安装与测试

```bash
cd kernel
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## 使用

```bash
optree build examples/razorback_demo.json --workdir .optree
# 输出 .optree/out/razorback.fbx
```

## OpTree v1 节点

| op | inputs | params | 说明 |
|---|---|---|---|
| `primitive` | - | `type: box/cylinder`, `size`, `radius`, `depth`, `vertices`, `location` | 参数化基础体，单位米 |
| `bevel` | [src] | `width`, `segments` | 倒角 |
| `boolean_subtract` | [target, cutter] | - | 精确布尔减（开槽/挖洞） |
| `scale_to` | [src] | `length_m` | 等比缩放到指定最长边 |
| `export_fbx` | [src] | `filename` | 导出 FBX |

中间产物缓存于 `<workdir>/cache/<content-hash>.glb`，同参数同输入必命中缓存。
````

Modify 根 `README.md`：追加一行 `- `kernel/`：OpTree 执行内核，见 [kernel/README.md](kernel/README.md)`。

- [ ] **Step 2: 全量最终回归**

Run: `cd kernel && .venv/bin/pytest -v`
Expected: 全部 passed（26 个测试）

- [ ] **Step 3: Commit**

```bash
git add kernel/README.md README.md
git commit -m "docs(kernel): usage and node reference"
```

---

## 后续计划（不在本计划内）

- 计划 2：编排服务（自然语言 → LLM → OpTree diff + schema 校验回喂 + AI 自检闭环）
- 计划 3：部件库（snap 接口定义 + `attach_part` 节点 + 首批 10–20 件精模）
- 计划 4：UI 壳（预览视口 + 指令框 + 圈选 + OpTree 只读展示）
