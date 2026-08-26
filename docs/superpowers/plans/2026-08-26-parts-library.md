# 部件库与装配节点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给内核加 `attach_part` 装配节点 + 部件库基础设施（清单、加载器、3 个示例精模），并让编排服务把可用部件列表注入 prompt、明确"装配 vs 切割"的使用规则。

**Architecture:** kernel 侧：`schema.py` 加 `AttachPartNode` → `parts.py`（PartsIndex 清单加载/校验/内容哈希）→ `emit.py` 加 `emit_attach_part` → `engine.build(tree, workdir, parts_dir=None)` 接线。`parts/` 目录：`index.json` 清单 + `build_parts.py`（Blender 脚本程序化生成示例件）。orchestrator 侧：prompt 注入部件列表与使用规则，`cli build --parts` 透传。

**Tech Stack:** 同既有栈（Python ≥3.11、pydantic、Blender headless）；零新增第三方依赖。

**Spec:** `docs/superpowers/specs/2026-08-25-ex-co-model-design.md`（第 3 节 Source 节点的 `attach_part`、第 4 节部件库）

**动机（真实端到端验证的结论）：** v1 内核没有装配能力，LLM 把"双引擎"用 `boolean_subtract` 从船体减掉。本计划从两个方向修：内核给正确的工具（`attach_part`），prompt 给正确的规则。

## Global Constraints

- 零新增第三方依赖（kernel 与 orchestrator 都是）
- 单位米；`attach_part` 的 `location`/`rotation_deg` 在父节点（世界）坐标系
- `attach_part` 节点的缓存键必须包含部件文件内容哈希——部件文件变了，缓存必须失效
- 部件库位置不做硬编码：`build(tree, workdir, parts_dir)` 显式传入；CLI 默认 `./parts`
- 本计划只做 3 个程序化示例件（pdc_turret / engine_nozzle / comm_antenna）验证管线；真正的手工精模是美术工作，不在本计划
- 代码标识符与注释用英文；commit message 用英文 conventional commits
- TDD：先写失败测试，再写最小实现，每个 Task 结束必须 commit
- kernel 代码在 `kernel/`，orchestrator 代码在 `orchestrator/`，部件库在 `parts/`

---

### Task 1: schema 加 attach_part + 部件清单加载器

**Files:**
- Modify: `kernel/optree/schema.py`（加 `AttachPartParams`、`AttachPartNode`，并入 `Node` union）
- Create: `kernel/optree/parts.py`
- Test: `kernel/tests/test_parts.py`
- Test: `kernel/tests/test_schema.py`（追加 attach_part 用例）

**Interfaces:**
- Consumes: 既有 `NodeBase`/`Node`/`OpTree`
- Produces:
  - `optree.schema.AttachPartParams`：`part: str`、`location: tuple3=(0,0,0)`、`rotation_deg: tuple3=(0,0,0)`、`scale: FiniteFloat=Field(default=1.0, gt=0)`、`part_hash: str | None = None`（engine 注入，用户不写）
  - `optree.schema.AttachPartNode`：`op="attach_part"`、`inputs` 恰好 1 个（父节点）
  - `optree.parts.PartsIndex`：`.load(parts_dir) -> PartsIndex`、`.resolve(name) -> Path`（未知部件抛 `OpTreeError`）、`.content_hash(name) -> str`、`.names() -> list[str]`

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/test_parts.py`:

```python
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
```

Append to `kernel/tests/test_schema.py`:

```python
def test_attach_part_node_parses():
    tree = OpTree.model_validate({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box"}},
            "armed": {
                "op": "attach_part",
                "inputs": ["hull"],
                "params": {"part": "pdc_turret", "location": [0, 0, 2]},
            },
        }
    })
    node = tree.nodes["armed"]
    assert node.params.part == "pdc_turret"
    assert node.params.scale == 1.0
    assert node.params.part_hash is None


def test_attach_part_requires_exactly_one_input():
    import pytest
    with pytest.raises(ValidationError):
        OpTree.model_validate({
            "nodes": {
                "bad": {"op": "attach_part", "inputs": [], "params": {"part": "x"}},
            }
        })


def test_attach_part_rejects_zero_scale():
    import pytest
    with pytest.raises(ValidationError):
        OpTree.model_validate({
            "nodes": {
                "hull": {"op": "primitive", "params": {"type": "box"}},
                "bad": {
                    "op": "attach_part",
                    "inputs": ["hull"],
                    "params": {"part": "x", "scale": 0},
                },
            }
        })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_parts.py tests/test_schema.py -v`
Expected: ERROR/FAIL（`No module named 'optree.parts'`；schema 新用例报 ValidationError）

- [ ] **Step 3: 实现**

Modify `kernel/optree/schema.py`——在 `ExportFbxParams` 之后加：

```python
class AttachPartParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part: str
    location: tuple[FiniteFloat, FiniteFloat, FiniteFloat] = (0.0, 0.0, 0.0)
    rotation_deg: tuple[FiniteFloat, FiniteFloat, FiniteFloat] = (0.0, 0.0, 0.0)
    scale: FiniteFloat = Field(default=1.0, gt=0)
    part_hash: str | None = None  # injected by the engine, not by users
```

加节点类（放在 `ScaleToNode` 之后）：

```python
class AttachPartNode(NodeBase):
    op: Literal["attach_part"]
    inputs: list[str] = Field(min_length=1, max_length=1)  # the parent
    params: AttachPartParams
```

把 `AttachPartNode` 加进 `Node` 的 Union 列表。

注意：`FiniteFloat` 已在 schema.py 中定义（final-review 修复引入）。如果实际定义名不同，沿用文件中现有的有限浮点类型写法。

Create `kernel/optree/parts.py`:

```python
import hashlib
import json
from pathlib import Path

from optree.errors import OpTreeError


class PartsIndex:
    """Registry of library parts backed by <parts_dir>/index.json."""

    def __init__(self, parts: dict[str, dict], root: Path):
        self._parts = parts
        self._root = root

    @classmethod
    def load(cls, parts_dir: str | Path) -> "PartsIndex":
        root = Path(parts_dir)
        index_path = root / "index.json"
        if not index_path.exists():
            raise OpTreeError(f"parts index not found: {index_path}")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        parts = data.get("parts", {})
        for name, entry in parts.items():
            glb = root / entry["file"]
            if not glb.exists():
                raise OpTreeError(f"part {name!r} file missing: {glb}")
        return cls(parts, root)

    def resolve(self, name: str) -> Path:
        if name not in self._parts:
            raise OpTreeError(
                f"unknown part {name!r}; available: {sorted(self._parts)}"
            )
        return self._root / self._parts[name]["file"]

    def content_hash(self, name: str) -> str:
        return hashlib.sha256(self.resolve(name).read_bytes()).hexdigest()[:16]

    def names(self) -> list[str]:
        return sorted(self._parts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_parts.py tests/test_schema.py -v`
Expected: 全部 passed（parts 5 + schema 原有 10 + 新增 3 = 18）

- [ ] **Step 5: Commit**

```bash
git add kernel/optree/schema.py kernel/optree/parts.py kernel/tests/test_parts.py kernel/tests/test_schema.py
git commit -m "feat(kernel): attach_part node schema and parts index"
```

---

### Task 2: attach_part 代码生成器 + engine 接线

**Files:**
- Modify: `kernel/optree/emit.py`（加 `emit_attach_part`）
- Modify: `kernel/optree/engine.py`（`build` 加 `parts_dir` 参数、attach_part 分发、part_hash 注入）
- Test: `kernel/tests/test_emit.py`（追加用例）
- Test: `kernel/tests/test_engine.py`（追加用例，含 blender 集成）

**Interfaces:**
- Consumes: Task 1 的 `AttachPartNode`/`AttachPartParams`/`PartsIndex`；既有 emit 辅助（`_import_glb`、`_export_glb`、`_fmt_num`、`_fmt_vec3`——以 emit.py 现有实现为准）
- Produces:
  - `optree.emit.emit_attach_part(out: str, parent: str, part_path: str, p: AttachPartParams) -> str`
  - `optree.engine.build(tree, workdir, parts_dir=None) -> BuildResult`（树含 attach_part 而 parts_dir 为 None 时抛 `OpTreeError`）

- [ ] **Step 1: 写失败测试**

Append to `kernel/tests/test_emit.py`:

```python
from optree.emit import emit_attach_part
from optree.schema import AttachPartParams


def test_emit_attach_part_imports_both_and_transforms():
    code = emit_attach_part(
        "/tmp/out.glb", "/tmp/parent.glb", "/lib/turret.glb",
        AttachPartParams(part="pdc_turret", location=(0, 0, 2),
                         rotation_deg=(0, 90, 0), scale=1.5),
    )
    assert code.index("/tmp/parent.glb") < code.index("/lib/turret.glb")
    assert "import_scene.gltf" in code
    assert "math.radians" in code
    assert "(0, 0, 2)" in code
    assert "(0, 90, 0)" in code
    assert "1.5" in code
    assert "export_scene.gltf" in code
```

Append to `kernel/tests/test_engine.py`:

```python
import json

import pytest

from optree.errors import OpTreeError


def attach_tree() -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "armed": {
                "op": "attach_part",
                "inputs": ["hull"],
                "params": {"part": "pdc_turret", "location": [0, 0, 2]},
            },
            "out": {
                "op": "export_fbx",
                "inputs": ["armed"],
                "params": {"filename": "armed.fbx"},
            },
        }
    })


@pytest.fixture
def mini_parts(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "turret.glb").write_bytes(b"fake-glb")
    (parts / "index.json").write_text(json.dumps({
        "parts": {"pdc_turret": {"file": "turret.glb", "description": "t"}}
    }), encoding="utf-8")
    return parts


def test_attach_part_requires_parts_dir(tmp_path):
    with pytest.raises(OpTreeError, match="parts_dir"):
        build(attach_tree(), tmp_path / "w")


def test_attach_part_injects_part_hash_into_key(tmp_path, mini_parts):
    """part file content changes -> node key changes -> cache invalidates."""
    from optree.keys import node_key
    tree = attach_tree()
    node = tree.nodes["armed"]
    idx1 = PartsIndex.load(mini_parts)
    node.params.part_hash = idx1.content_hash("pdc_turret")
    k1 = node_key(node, ["hullkey"])
    (mini_parts / "turret.glb").write_bytes(b"fake-glb-v2")
    node.params.part_hash = idx1.content_hash("pdc_turret")
    assert node_key(node, ["hullkey"]) != k1


@requires_blender
def test_build_with_real_library(tmp_path):
    """End-to-end: attach a real library part, export fbx containing 2+ objects."""
    import subprocess
    repo_parts = __import__("pathlib").Path(__file__).parent.parent.parent / "parts"
    result = build(attach_tree(), tmp_path / "w", parts_dir=repo_parts)
    assert result.exports[0].exists()
    # count meshes inside the attached-node glb via blender
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        f"bpy.ops.import_scene.gltf(filepath={str(result.glbs['armed'])!r})\n"
        "n = len([o for o in bpy.context.scene.objects if o.type == 'MESH'])\n"
        f"open({str(tmp_path / 'count.txt')!r}, 'w').write(str(n))\n"
    )
    subprocess.run(
        ["blender", "-b", "--factory-startup", "--python", str(probe)],
        check=True, capture_output=True,
    )
    assert int((tmp_path / "count.txt").read_text()) >= 2
```

（`test_engine.py` 顶部需能引用 `PartsIndex`——在文件头部 import 区加 `from optree.parts import PartsIndex`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_emit.py tests/test_engine.py -v`
Expected: 新用例 FAIL/ERROR（`emit_attach_part` 不存在；`build()` 没有 `parts_dir` 参数）。注意 `test_build_with_real_library` 依赖 Task 3 的 `parts/` 目录，此刻会失败——本任务先让它 ERROR，Task 3 完成后转绿。

- [ ] **Step 3: 实现 emit_attach_part**

Append to `kernel/optree/emit.py`:

```python
def emit_attach_part(out: str, parent: str, part_path: str, p: "AttachPartParams") -> str:
    """Import parent + library part, place the part, export combined scene."""
    return (
        _import_glb(parent)
        + "bpy.ops.object.select_all(action='DESELECT')\n"
        + _import_glb(part_path)
        + "import math\n"
        + f"loc = {_fmt_vec3(p.location)}\n"
        + f"rot = tuple(math.radians(a) for a in {_fmt_vec3(p.rotation_deg)})\n"
        + f"s = {_fmt_num(p.scale)}\n"
        + "for o in imported:\n"
        + "    o.location = tuple(a + b for a, b in zip(o.location, loc))\n"
        + "    o.rotation_euler = tuple(a + b for a, b in zip(o.rotation_euler, rot))\n"
        + "    o.scale = tuple(a * s for a in o.scale)\n"
        + _export_glb(out)
    )
```

并在文件头部 import 区加 `from optree.schema import AttachPartParams`（并入现有 schema import 行）。

- [ ] **Step 4: 实现 engine 接线**

Modify `kernel/optree/engine.py`:

1. import 区加 `from optree.errors import OpTreeError` 和 `from optree.parts import PartsIndex`
2. 签名改为 `def build(tree: OpTree, workdir: Path, parts_dir: Path | None = None) -> BuildResult:`
3. 在 `workdir = Path(workdir).resolve()` 之后加：

```python
    index = None
    if any(n.op == "attach_part" for n in tree.nodes.values()):
        if parts_dir is None:
            raise OpTreeError("tree uses attach_part; pass parts_dir")
        index = PartsIndex.load(parts_dir)
```

4. 在 key 计算循环里，`key = node_key(...)` 之前加：

```python
        if node.op == "attach_part":
            node.params.part_hash = index.content_hash(node.params.part)
```

5. 在 dirty 执行的 if/elif 链中，`elif node.op == "scale_to":` 之后加：

```python
            elif node.op == "attach_part":
                script += emit.emit_attach_part(
                    str(glbs[name]), str(glbs[node.inputs[0]]),
                    str(index.resolve(node.params.part)), node.params,
                )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_emit.py tests/test_engine.py -v`
Expected: 除 `test_build_with_real_library`（等 Task 3）外全部 passed

- [ ] **Step 6: Commit**

```bash
git add kernel/optree/emit.py kernel/optree/engine.py kernel/tests/test_emit.py kernel/tests/test_engine.py
git commit -m "feat(kernel): emit and engine wiring for attach_part with part hashing"
```

---

### Task 3: 部件库脚手架 + 3 个程序化示例件

**Files:**
- Create: `parts/index.json`
- Create: `parts/build_parts.py`
- Create: `parts/.gitignore`（忽略生成的 `*.glb`——但示例件需要进 git 供测试用，见 Step 3 决策）
- Test: `kernel/tests/test_parts_build.py`

**Interfaces:**
- Consumes: Task 1 的 `PartsIndex`
- Produces: `parts/` 目录含 `index.json` + 3 个 glb（`pdc_turret.glb`、`engine_nozzle.glb`、`comm_antenna.glb`），由 `blender -b --factory-startup --python parts/build_parts.py` 再生成

**决策（写进计划，执行者照做）：** 示例 glb **提交进 git**（二进制小文件，让测试和 fresh clone 直接可用），不建 `parts/.gitignore`。后续手工精模也提交。

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/test_parts_build.py`:

```python
import shutil
import subprocess
from pathlib import Path

from optree.parts import PartsIndex
from tests.conftest import requires_blender

PARTS_DIR = Path(__file__).parent.parent.parent / "parts"


@requires_blender
def test_build_parts_regenerates_glbs(tmp_path):
    """The generator script must produce all 3 glbs into a copied parts dir."""
    work = tmp_path / "parts"
    work.mkdir()
    shutil.copy(PARTS_DIR / "index.json", work / "index.json")
    script = PARTS_DIR / "build_parts.py"
    subprocess.run(
        ["blender", "-b", "--factory-startup", "--python", str(script), "--", str(work)],
        check=True, capture_output=True,
    )
    idx = PartsIndex.load(work)
    assert sorted(idx.names()) == ["comm_antenna", "engine_nozzle", "pdc_turret"]
    for name in idx.names():
        assert idx.resolve(name).stat().st_size > 500  # real geometry, not empty
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_parts_build.py -v`
Expected: FAIL（`parts/index.json` 不存在）

- [ ] **Step 3: 实现部件库**

Create `parts/index.json`:

```json
{
  "parts": {
    "pdc_turret": {
      "file": "pdc_turret.glb",
      "description": "point defense cannon turret: round base + twin barrels",
      "snap": {"mount": "flat surface, barrels point +Z", "approx_size_m": [1.2, 1.2, 1.6]}
    },
    "engine_nozzle": {
      "file": "engine_nozzle.glb",
      "description": "main engine nozzle bell, throat faces -Z",
      "snap": {"mount": "engine block aft face", "approx_size_m": [2.0, 2.0, 2.5]}
    },
    "comm_antenna": {
      "file": "comm_antenna.glb",
      "description": "thin comm mast with dish",
      "snap": {"mount": "hull spine", "approx_size_m": [0.3, 0.3, 3.0]}
    }
  }
}
```

Create `parts/build_parts.py`:

```python
"""Regenerate the sample library parts. Run:
blender -b --factory-startup --python parts/build_parts.py -- <output_dir>
"""
import math
import sys
from pathlib import Path

import bpy

OUT_DIR = Path(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else Path("parts")


def clean():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def cyl(radius, depth, loc=(0, 0, 0), rot_deg=(0, 0, 0), vertices=24):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    obj = bpy.context.active_object
    obj.rotation_euler = tuple(math.radians(a) for a in rot_deg)
    return obj


def cone(r1, r2, depth, loc=(0, 0, 0), vertices=24):
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=r1, radius2=r2,
                                    depth=depth, location=loc)
    return bpy.context.active_object


def box(size, loc=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.active_object
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def export(name):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(OUT_DIR / f"{name}.glb"), export_format="GLB")


def build_pdc_turret():
    cyl(0.6, 0.3, loc=(0, 0, 0.15))                     # base ring
    box((0.9, 0.5, 0.5), loc=(0, 0, 0.55))              # housing
    cyl(0.06, 0.9, loc=(0, -0.12, 1.15), rot_deg=(90, 0, 0))  # barrel L
    cyl(0.06, 0.9, loc=(0, 0.12, 1.15), rot_deg=(90, 0, 0))   # barrel R
    export("pdc_turret")


def build_engine_nozzle():
    cone(1.0, 0.45, 2.5)                                 # bell
    cyl(0.45, 0.3, loc=(0, 0, 1.35))                     # throat mount
    export("engine_nozzle")


def build_comm_antenna():
    cyl(0.05, 2.6, loc=(0, 0, 1.3))                      # mast
    cone(0.5, 0.05, 0.4, loc=(0, 0, 2.8))                # dish
    export("comm_antenna")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for builder in (build_pdc_turret, build_engine_nozzle, build_comm_antenna):
        clean()
        builder()


main()
```

生成并提交示例件：

```bash
blender -b --factory-startup --python parts/build_parts.py -- parts/
```

Expected: `parts/` 下出现 3 个 glb。

- [ ] **Step 4: 跑测试确认通过（含 Task 2 遗留的集成测试）**

Run: `cd kernel && .venv/bin/pytest -v`
Expected: 全部 passed（含 `test_build_parts_regenerates_glbs` 和 Task 2 的 `test_build_with_real_library`）

- [ ] **Step 5: Commit**

```bash
git add parts/ kernel/tests/test_parts_build.py
git commit -m "feat(parts): sample library with 3 procedural parts and generator"
```

---

### Task 4: orchestrator 接线（prompt 部件注入 + 使用规则 + --parts）+ 回归

**Files:**
- Modify: `orchestrator/orchestrator/prompts.py`（SYSTEM_PROMPT 加 attach_part 文档与规则；`build_messages` 加 `available_parts` 参数）
- Modify: `orchestrator/orchestrator/core.py`（`run_apply` 透传 `available_parts`）
- Modify: `orchestrator/orchestrator/session.py`（`apply` 透传）
- Modify: `orchestrator/orchestrator/cli.py`（`--parts` 参数，默认 `Path("parts")`；apply 时加载部件名列表注入）
- Modify: `kernel/README.md`（节点表加 attach_part 行）
- Modify: `orchestrator/README.md`（用法加 --parts 说明）
- Test: `orchestrator/tests/test_prompts.py`（追加用例）

**Interfaces:**
- Consumes: 全部前置任务
- Produces:
  - `build_messages(instruction, current_tree, available_parts: list[str] | None = None)`
  - `run_apply(llm, instruction, current_tree, max_rounds=3, available_parts=None)`
  - `Session.apply(llm, instruction, available_parts=None)`
  - CLI：`apply`/`build` 增加 `--parts PATH`（默认 `./parts`）；apply 时若目录存在则注入 `PartsIndex.load(...).names()`

- [ ] **Step 1: 写失败测试**

Append to `orchestrator/tests/test_prompts.py`:

```python
def test_system_prompt_documents_attach_part_rules():
    assert "attach_part" in SYSTEM_PROMPT
    # the anti-misuse rule: boolean_subtract is only for cutting
    assert "never" in SYSTEM_PROMPT.lower() or "only" in SYSTEM_PROMPT.lower()


def test_build_messages_lists_available_parts():
    msgs = build_messages("加一门炮", None, available_parts=["pdc_turret", "engine_nozzle"])
    assert "pdc_turret" in msgs[1]["content"]
    assert "engine_nozzle" in msgs[1]["content"]


def test_build_messages_without_parts_omits_section():
    msgs = build_messages("一艘船", None)
    assert "Available parts" not in msgs[1]["content"]
```

Append to `orchestrator/tests/test_core.py`:

```python
def test_available_parts_reach_prompt():
    llm = FakeLLMClient([VALID_TREE])
    run_apply(llm, "加一门炮", None, available_parts=["pdc_turret"])
    assert "pdc_turret" in llm.calls[0][1]["content"]
```

Append to `orchestrator/tests/test_cli.py`:

```python
def test_build_passes_parts_dir(tmp_path):
    """build with attach_part tree and --parts pointing at the repo library."""
    session = tmp_path / "s.json"
    session.write_text(json.dumps({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "armed": {
                "op": "attach_part",
                "inputs": ["hull"],
                "params": {"part": "pdc_turret", "location": [0, 0, 2]},
            },
            "out": {"op": "export_fbx", "inputs": ["armed"],
                    "params": {"filename": "armed.fbx"}},
        }
    }), encoding="utf-8")
    repo_parts = __import__("pathlib").Path(__file__).parent.parent.parent / "parts"
    assert main(["build", "--session", str(session),
                 "--workdir", str(tmp_path / "b"), "--parts", str(repo_parts)]) == 0
    assert (tmp_path / "b" / "out" / "armed.fbx").exists()
```

（这个测试需要 Blender——给它加 `@requires_blender` 装饰器。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest -v`
Expected: 新用例 FAIL（prompt 无 attach_part 文档；`available_parts` 参数不存在；`--parts` 不存在）

- [ ] **Step 3: 实现 prompts.py 修改**

`SYSTEM_PROMPT` 的节点列表中，`export_fbx` 之前插入：

```
- attach_part: inputs [parent]. params: part (library part name), location [x,y,z], \
rotation_deg [x,y,z], scale (>0). Attaches a precision library part onto the parent.
```

并在 "When modifying an existing tree..." 之前插入规则段：

```
Rules:
- To ADD a component (engine, turret, antenna...), ALWAYS use attach_part with a \
library part. NEVER use boolean_subtract to add something — it only removes material.
- boolean_subtract is ONLY for cutting slots/holes out of a target.
```

`build_messages` 签名与部件注入：

```python
def build_messages(instruction: str, current_tree: OpTree | None,
                   available_parts: list[str] | None = None) -> list[dict]:
    user = ""
    if current_tree is not None:
        ...（保持现状）
    if available_parts:
        user += "Available parts: " + ", ".join(available_parts) + "\n\n"
    user += f"Instruction: {instruction}"
    ...
```

- [ ] **Step 4: 实现 core/session/cli 透传**

`core.py`：`run_apply(..., available_parts: list[str] | None = None)`，传给 `build_messages(instruction, current_tree, available_parts)`。

`session.py`：`apply(self, llm, instruction, available_parts=None)`，传给 `run_apply(llm, instruction, self.tree, available_parts=available_parts)`。

`cli.py`：
- `common` parser 加 `--parts`，默认 `Path("parts")`
- apply 分支：

```python
            from optree.parts import PartsIndex
            parts = None
            if args.parts.exists():
                parts = PartsIndex.load(args.parts).names()
            result = session.apply(client, args.instruction, available_parts=parts)
```

（import 放文件头部。）

- build 分支：`build(session.tree, args.workdir, parts_dir=args.parts if args.parts.exists() else None)`

- [ ] **Step 5: 更新两个 README 的节点/用法表**

`kernel/README.md` 节点表加一行：

```
| `attach_part` | [parent] | `part`, `location`, `rotation_deg`, `scale` | 装配部件库精模到母体 |
```

`orchestrator/README.md` 使用段加：

```bash
orchestrator apply "在船尾装两个引擎喷口"     # 若 ./parts 存在，部件列表自动注入 prompt
orchestrator build --parts ./parts           # attach_part 需要部件库（默认 ./parts）
```

- [ ] **Step 6: 全量回归**

```bash
cd kernel && .venv/bin/pytest -v
cd ../orchestrator && ../kernel/.venv/bin/pytest -v
```

Expected: kernel 全部 passed（34 + 新增 13 = 47）；orchestrator 全部 passed（32 + 新增 4 = 36，含 blender-gated 全真实执行）

- [ ] **Step 7: Commit**

```bash
git add orchestrator/ kernel/README.md
git commit -m "feat(orchestrator): inject parts into prompt, wire --parts through cli"
```

---

## 真实 LLM 端到端验证（手动，计入验收）

在仓库根目录（`.env` 已配好）：

```bash
kernel/.venv/bin/orchestrator apply "一艘太空护卫舰，船尾装两个引擎喷口，背上装一根通讯天线"
kernel/.venv/bin/orchestrator apply "全长改成40米，船身侧面开一个机库口"
kernel/.venv/bin/orchestrator build
```

验收标准：
1. 第一条的树里引擎/天线是 `attach_part` 节点（不是 boolean_subtract）
2. 第二条保持部件节点不变，只改 scale_to + 新增切割
3. FBX 构建成功，且包含船体 + 喷口×2 + 天线（可用 Blender 打开验证对象数 ≥4）

## 后续计划（不在本计划内）

- 计划 4：UI 壳 + 渲染管线 + VLM 自检闭环
- 部件库扩充（手工精模 10–20 件，美术工作，随游戏资产清单驱动）
