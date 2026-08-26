# UI 壳 + 渲染管线 + VLM 自检闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 ex-co-model 加渲染预览（headless Blender 自动取景出 PNG）、VLM 自检闭环（渲染图 vs 意图，不像就自动带批评重试）、本地 Web UI（Three.js 3D 视口 + 指令输入 + OpTree 展示）。

**Architecture:** kernel 加 `render.py`（GLB → PNG，自动包围盒取景 + 双灯 + 灰色世界光）。orchestrator 加：`preview` 命令（build + render）；`llm.complete_with_image`（OpenAI 视觉格式 base64 data URL）+ `check.py`（vision_check → Verdict）+ `apply --check`（自检失败带批评重试 ≤2 轮）；`server.py`（stdlib http.server，零新依赖）+ `static/index.html`（Three.js CDN）。

**Tech Stack:** 同既有栈；**零新增 Python 依赖**（Web 服务用 stdlib `http.server`；前端 Three.js 走 CDN，不进 Python 依赖）。

**Spec:** `docs/superpowers/specs/2026-08-25-ex-co-model-design.md`（第 4 节 UI 壳与 AI 自检闭环、第 5 节数据流第 5 步）

## 与 spec 的有意偏差（已决策）

**UI 壳用本地 Web 应用（stdlib HTTP + 浏览器 + Three.js CDN），不用 Tauri/Electron。** 理由：后端全 Python，为一个壳引入 Rust/Node 工具链违反 YAGNI；能力等价（预览视口 + 指令输入 + OpTree 展示），后续仍可再包壳。

## Global Constraints

- 零新增 Python 第三方依赖（前端 Three.js 走 unpkg CDN，不计）
- 渲染引擎 id 用 `BLENDER_EEVEE`（Blender 5.2 实测；`BLENDER_EEVEE_NEXT` 已不存在）
- VLM 自检是**尽力而为**：模型不支持图片输入时打印 warning 并跳过，绝不能因此阻断建模主流程
- spec §7 铁律不变：任何失败都是结构化 `error:` 消息，不是 traceback
- 代码标识符与注释用英文；commit message 用英文 conventional commits
- TDD：先写失败测试，再写最小实现，每个 Task 结束必须 commit

---

### Task 1: kernel 渲染管线（GLB → PNG）

**Files:**
- Create: `kernel/optree/render.py`
- Test: `kernel/tests/test_render.py`

**Interfaces:**
- Consumes: `optree.blender_session.run_blender_script`、`optree.errors.BlenderError`
- Produces: `optree.render.render_glb(glb: str | Path, out_png: str | Path, workdir: Path, size: int = 1024) -> Path`——自动包围盒取景，输出 PNG；渲染无产出抛 `BlenderError`

- [ ] **Step 1: 写失败测试**

Create `kernel/tests/test_render.py`:

```python
from optree.engine import build
from optree.render import render_glb
from optree.schema import OpTree
from tests.conftest import requires_blender


@requires_blender
def test_render_glb_produces_nontrivial_png(tmp_path):
    tree = OpTree.model_validate({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "out": {"op": "export_fbx", "inputs": ["hull"],
                    "params": {"filename": "hull.fbx"}},
        }
    })
    result = build(tree, tmp_path / "b")
    png = render_glb(result.glbs["hull"], tmp_path / "preview.png", tmp_path / "r")
    assert png.exists()
    # a uniformly-black or empty render compresses to a few KB; real geometry > 20KB
    assert png.stat().st_size > 20_000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd kernel && .venv/bin/pytest tests/test_render.py -v`
Expected: ERROR（`No module named 'optree.render'`）

- [ ] **Step 3: 实现 render.py**

Create `kernel/optree/render.py`:

```python
"""Headless preview rendering: GLB in, framed PNG out."""

from pathlib import Path

from optree.blender_session import run_blender_script
from optree.errors import BlenderError

# bbox auto-framing; two area lights + gray world. energies scale with scene size.
_RENDER_TEMPLATE = '''
import bpy
from mathutils import Vector

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={glb!r})

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
mins = Vector((1e18, 1e18, 1e18))
maxs = Vector((-1e18, -1e18, -1e18))
for o in meshes:
    for corner in o.bound_box:
        w = o.matrix_world @ Vector(corner)
        mins = Vector(map(min, mins, w))
        maxs = Vector(map(max, maxs, w))
center = (mins + maxs) / 2
dims = maxs - mins
radius = max(max(dims.x, dims.y, dims.z) / 2, 0.5)

mat = bpy.data.materials.new("preview")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.72, 0.75, 0.8, 1)
bsdf.inputs["Roughness"].default_value = 0.55
for o in meshes:
    if not o.data.materials:
        o.data.materials.append(mat)

dist = radius * 4.0

def area_light(offset, energy):
    bpy.ops.object.light_add(type="AREA", location=center + offset)
    lamp = bpy.context.active_object
    lamp.data.energy = energy
    lamp.data.size = radius * 2
    lamp.rotation_euler = (center - lamp.location).to_track_quat("-Z", "Y").to_euler()

area_light(Vector((dist * 0.7, -dist * 0.7, dist * 0.7)), radius * radius * 60)
area_light(Vector((-dist * 0.7, dist * 0.7, -dist * 0.2)), radius * radius * 25)

bpy.ops.object.camera_add(location=center + Vector((dist * 0.75, -dist * 0.75, dist * 0.5)))
cam = bpy.context.active_object
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.35, 0.4, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.5
bpy.context.scene.world = world

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = {size}
scene.render.resolution_y = {size} * 9 // 16
scene.render.filepath = {out!r}
bpy.ops.render.render(write_still=True)
'''


def render_glb(glb: str | Path, out_png: str | Path, workdir: Path,
               size: int = 1024) -> Path:
    """Render a framed preview of a glb to png. Raises BlenderError on failure."""
    out = Path(out_png).resolve()
    script = _RENDER_TEMPLATE.format(glb=str(Path(glb).resolve()), out=str(out), size=size)
    run_blender_script(script, Path(workdir))
    if not out.exists():
        raise BlenderError(f"render produced no output: {out}")
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd kernel && .venv/bin/pytest tests/test_render.py -v`
Expected: 1 passed（真实 Blender 渲染）

- [ ] **Step 5: Commit**

```bash
git add kernel/optree/render.py kernel/tests/test_render.py
git commit -m "feat(kernel): headless glb preview rendering with auto framing"
```

---

### Task 2: orchestrator `preview` 命令

**Files:**
- Modify: `orchestrator/orchestrator/cli.py`（加 `preview` 子命令）
- Create: `orchestrator/orchestrator/pipeline.py`（build + 定位最终 glb + render 的共用逻辑）
- Test: `orchestrator/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `optree.engine.build`、`optree.render.render_glb`、`optree.graph.topo_order`、`Session`
- Produces:
  - `orchestrator.pipeline.build_and_render(session: Session, workdir: Path, parts_dir: Path | None) -> Path`（返回 preview PNG 路径；无树抛 `OrchestratorError`）
  - `orchestrator.pipeline.final_glb(tree: OpTree, result: BuildResult) -> Path`（export 节点的输入 glb；无 export 节点取拓扑序最后一个）
  - CLI：`orchestrator preview [--session PATH] [--workdir DIR] [--parts DIR]`，打印 PNG 路径

- [ ] **Step 1: 写失败测试**

Create `orchestrator/tests/test_pipeline.py`:

```python
import json

import pytest

from optree.schema import OpTree

from orchestrator.errors import OrchestratorError
from orchestrator.pipeline import build_and_render, final_glb
from orchestrator.session import Session
from tests.conftest import requires_blender

TREE = {
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "shaped": {"op": "bevel", "inputs": ["hull"], "params": {"width": 0.3}},
        "out": {"op": "export_fbx", "inputs": ["shaped"],
                "params": {"filename": "ship.fbx"}},
    }
}


def test_final_glb_prefers_export_input(tmp_path):
    tree = OpTree.model_validate(TREE)
    from optree.engine import BuildResult
    fake = BuildResult(glbs={"hull": tmp_path / "a.glb", "shaped": tmp_path / "b.glb"})
    assert final_glb(tree, fake) == tmp_path / "b.glb"


def test_build_and_render_without_tree_raises(tmp_path):
    with pytest.raises(OrchestratorError, match="no session tree"):
        build_and_render(Session(tmp_path / "nope.json"), tmp_path / "w", None)


@requires_blender
def test_build_and_render_produces_png(tmp_path):
    session_path = tmp_path / "s.json"
    session_path.write_text(json.dumps(TREE), encoding="utf-8")
    png = build_and_render(Session(session_path), tmp_path / "w", None)
    assert png.exists() and png.stat().st_size > 20_000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_pipeline.py -v`
Expected: ERROR（`No module named 'orchestrator.pipeline'`）

- [ ] **Step 3: 实现 pipeline.py + cli 接线**

Create `orchestrator/orchestrator/pipeline.py`:

```python
from pathlib import Path

from optree.engine import BuildResult, build
from optree.graph import topo_order
from optree.render import render_glb
from optree.schema import OpTree

from orchestrator.errors import OrchestratorError
from orchestrator.session import Session


def final_glb(tree: OpTree, result: BuildResult) -> Path:
    """The glb representing the finished asset (input of the export node)."""
    for node in tree.nodes.values():
        if node.op == "export_fbx":
            return result.glbs[node.inputs[0]]
    return result.glbs[topo_order(tree)[-1]]


def build_and_render(session: Session, workdir: Path,
                     parts_dir: Path | None) -> Path:
    """Build the session tree and render a preview png. Returns the png path."""
    if session.tree is None:
        raise OrchestratorError(f"no session tree at {session.path}")
    result = build(session.tree, workdir, parts_dir=parts_dir)
    return render_glb(final_glb(session.tree, result),
                      Path(workdir) / "out" / "preview.png", workdir)
```

Modify `orchestrator/orchestrator/cli.py`：
- import 区加 `from orchestrator.pipeline import build_and_render`
- 在 `show` 子命令后加：

```python
    sub.add_parser("preview", parents=[common], help="build and render a preview png")
```

- 在 `elif args.cmd == "show":` 分支后加：

```python
        elif args.cmd == "preview":
            png = build_and_render(
                session, args.workdir,
                args.parts if args.parts.exists() else None)
            print(png)
```

注意：`preview` 需要 `--workdir`——把 `--workdir` 从 `build` 的 parser 移到 `common` parser（`common.add_argument("--workdir", type=Path, default=Path(".exco/build"))`），并从 `build` parser 删掉原来的那一行。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest -v`
Expected: 全部 passed（新增 3，含 1 个真实 Blender 测试）

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator/pipeline.py orchestrator/orchestrator/cli.py orchestrator/tests/test_pipeline.py
git commit -m "feat(orchestrator): preview command with build and render pipeline"
```

---

### Task 3: VLM 自检闭环

**Files:**
- Modify: `orchestrator/orchestrator/llm.py`（`LLMClient` 加 `complete_with_image`；`MoonshotClient` 实现；`FakeLLMClient` 支持）
- Create: `orchestrator/orchestrator/check.py`
- Modify: `orchestrator/orchestrator/cli.py`（`apply --check`）
- Test: `orchestrator/tests/test_check.py`
- Test: `orchestrator/tests/test_llm.py`（追加用例）

**Interfaces:**
- Consumes: 既有 llm/pipeline/session
- Produces:
  - `LLMClient.complete_with_image(text: str, image_path: Path) -> str`
  - `orchestrator.check.Verdict`（dataclass：`.ok: bool`、`.reason: str`）
  - `orchestrator.check.vision_check(llm, png: Path, instruction: str) -> Verdict`（LLM 返回非法 JSON 抛 `OrchestratorError`）
  - CLI：`apply --check`——apply 成功后 build+render+vision_check；不 ok 则把 reason 作为反馈再 apply 一轮并重新 build/render/check，最多 2 轮；vision 不可用（OrchestratorError 来自请求层）打 warning 跳过

- [ ] **Step 1: 写失败测试**

Create `orchestrator/tests/test_check.py`:

```python
import json
from pathlib import Path

import pytest

from orchestrator.check import Verdict, vision_check
from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient


def test_vision_check_ok(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-png")
    llm = FakeLLMClient(['{"ok": true}'])
    v = vision_check(llm, png, "一艘护卫舰")
    assert v.ok and v.reason == ""
    assert llm.image_calls[0][1] == png  # image path passed through


def test_vision_check_not_ok_with_reason(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-png")
    llm = FakeLLMClient(['{"ok": false, "reason": "missing engines"}'])
    v = vision_check(llm, png, "双引擎护卫舰")
    assert not v.ok
    assert "engines" in v.reason


def test_vision_check_bad_json_raises(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-png")
    llm = FakeLLMClient(["looks fine to me"])
    with pytest.raises(OrchestratorError, match="invalid verdict"):
        vision_check(llm, png, "一艘护卫舰")
```

Append to `orchestrator/tests/test_llm.py`:

```python
def test_moonshot_complete_with_image_builds_data_url(tmp_path, monkeypatch):
    import base64
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            class Msg:
                content = '{"ok": true}'
            class Choice:
                message = Msg()
            class Resp:
                choices = [Choice()]
            return Resp()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("orchestrator.llm.OpenAI", FakeOpenAI)
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-png")
    client = MoonshotClient(api_key="sk-test")
    out = client.complete_with_image("describe", png)
    assert out == '{"ok": true}'
    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(b"fake-png").decode()
    assert captured["response_format"] == {"type": "json_object"}


def test_fake_llm_client_image_calls(tmp_path):
    fake = FakeLLMClient(["img-resp"])
    out = fake.complete_with_image("look", tmp_path / "p.png")
    assert out == "img-resp"
    assert fake.image_calls == [("look", tmp_path / "p.png")]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_check.py tests/test_llm.py -v`
Expected: FAIL/ERROR（`complete_with_image`、`check` 模块不存在）

- [ ] **Step 3: 实现**

Modify `orchestrator/orchestrator/llm.py`：
- `LLMClient` 加方法签名 `def complete_with_image(self, text: str, image_path: Path) -> str: ...`（import Path）
- `MoonshotClient` 加：

```python
    def complete_with_image(self, text: str, image_path: Path) -> str:
        import base64
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        kwargs: dict = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as e:
            raise OrchestratorError(f"llm request failed: {e}") from e
        if not resp.choices or resp.choices[0].message.content is None:
            raise OrchestratorError("llm returned an empty response")
        return resp.choices[0].message.content
```

- `FakeLLMClient`：`__init__` 加 `self.image_calls: list[tuple[str, Path]] = []`；加方法：

```python
    def complete_with_image(self, text: str, image_path) -> str:
        self.image_calls.append((text, image_path))
        if not self.responses:
            raise AssertionError("FakeLLMClient ran out of queued responses")
        return self.responses.pop(0)
```

Create `orchestrator/orchestrator/check.py`:

```python
import json
from dataclasses import dataclass
from pathlib import Path

from orchestrator.errors import OrchestratorError
from orchestrator.llm import LLMClient

CHECK_PROMPT = """\
You are the quality checker of ex-co-model, an AI 3D modeling tool. The user \
asked for: "{instruction}"
Look at the rendered preview of the produced model. Judge ONLY structure: are \
the requested parts present and the proportions plausible? Ignore \
textures/colors entirely (models are untextured by design at this stage).
Respond with one json object: {{"ok": true}} or \
{{"ok": false, "reason": "<what is wrong, concretely>"}}.\
"""


@dataclass
class Verdict:
    ok: bool
    reason: str = ""


def vision_check(llm: LLMClient, png: Path, instruction: str) -> Verdict:
    raw = llm.complete_with_image(
        CHECK_PROMPT.format(instruction=instruction), png)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise OrchestratorError(f"invalid verdict json from vision model: {e}")
    return Verdict(ok=bool(data.get("ok")), reason=str(data.get("reason", "")))
```

Modify `orchestrator/orchestrator/cli.py`：
- `a.add_argument("--check", action="store_true", help="vision self-check after apply")`
- apply 分支在打印 `applied in ...` 之后加：

```python
            if args.check:
                from orchestrator.check import vision_check
                instruction = args.instruction
                for _attempt in (1, 2):
                    png = build_and_render(
                        session, args.workdir,
                        args.parts if args.parts.exists() else None)
                    try:
                        verdict = vision_check(client, png, instruction)
                    except OrchestratorError as e:
                        print(f"warning: vision check unavailable: {e}",
                              file=sys.stderr)
                        break
                    if verdict.ok:
                        print("self-check passed")
                        break
                    print(f"self-check failed: {verdict.reason}; retrying")
                    instruction = (f"The rendered result is wrong: "
                                   f"{verdict.reason}. Original request: "
                                   f"{args.instruction}")
                    result = session.apply(client, instruction,
                                           available_parts=parts)
                    print(f"re-applied in rounds={result.rounds}, "
                          f"nodes={len(result.tree.nodes)}")
```

（`build_and_render` 已在 Task 2 引入 import 区；`vision_check` 的 import 放文件头部。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest -v`
Expected: 全部 passed（新增 5）

- [ ] **Step 5: Commit**

```bash
git add orchestrator/
git commit -m "feat(orchestrator): vision self-check loop with retry on critique"
```

---

### Task 4: 本地 Web UI（stdlib 服务 + Three.js 视口）

**Files:**
- Create: `orchestrator/orchestrator/server.py`
- Create: `orchestrator/orchestrator/static/index.html`
- Modify: `orchestrator/orchestrator/cli.py`（加 `serve` 子命令）
- Modify: `orchestrator/pyproject.toml`（`[tool.setuptools.package-data]` 打包 static）
- Test: `orchestrator/tests/test_server.py`

**Interfaces:**
- Consumes: 全部前置任务
- Produces:
  - `orchestrator.server.make_server(session_path, workdir, parts_dir, llm_factory, host="127.0.0.1", port=8787) -> ThreadingHTTPServer`（可注入 llm_factory 供测试）
  - `orchestrator.server.serve(...) -> None`（阻塞式启动，打印地址）
  - CLI：`orchestrator serve [--port N] [--session ...] [--workdir ...] [--parts ...]`
  - HTTP 端点：
    - `GET /` → index.html
    - `GET /api/state` → `{"tree": {...}|null, "nodes": int, "parts": [str]}`
    - `GET /model.glb` → 当前资产最终 glb（构建过期则先重建）
    - `GET /preview.png` → 最新渲染图
    - `POST /api/apply`，body `{"instruction": "..."}` → 同步执行 apply+build+render，返回 `{"ok": true, "rounds": n, "nodes": n}` 或 `{"ok": false, "error": "..."}`

- [ ] **Step 1: 写失败测试**

Create `orchestrator/tests/test_server.py`:

```python
import json
import threading
from http.client import HTTPConnection

import pytest

from orchestrator.llm import FakeLLMClient
from orchestrator.server import make_server

VALID_TREE = json.dumps({
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"],
                "params": {"filename": "ship.fbx"}},
    }
})


@pytest.fixture
def server(tmp_path):
    fake = FakeLLMClient([VALID_TREE, VALID_TREE])
    srv = make_server(tmp_path / "s.json", tmp_path / "w", None,
                      llm_factory=lambda: fake, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, fake
    srv.shutdown()
    thread.join()


def _get(srv, path):
    conn = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def _post(srv, path, payload):
    conn = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=120)
    conn.request("POST", path, json.dumps(payload),
                 {"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, json.loads(body)


def test_index_served(server):
    status, body = _get(server[0], "/")
    assert status == 200
    assert b"<title>" in body


def test_state_empty_then_populated(server):
    srv, fake = server
    status, body = _get(srv, "/api/state")
    assert status == 200
    assert json.loads(body)["tree"] is None

    status, data = _post(srv, "/api/apply", {"instruction": "一艘护卫舰"})
    assert status == 200 and data["ok"] and data["nodes"] == 2

    status, body = _get(srv, "/api/state")
    state = json.loads(body)
    assert state["tree"] is not None and state["nodes"] == 2


def test_apply_error_is_structured(server):
    srv, fake = server
    fake.responses = ["garbage"] * 3
    status, data = _post(srv, "/api/apply", {"instruction": "x"})
    assert status == 200
    assert data["ok"] is False
    assert "error" in data


def test_404_for_unknown_path(server):
    status, _ = _get(server[0], "/nope")
    assert status == 404
```

注意：`POST /api/apply` 里会触发真实 build+render（Blender）——测试里 instruction 成功路径需要 Blender。给 `test_state_empty_then_populated` 加 `@requires_blender`（import from tests.conftest）。`test_apply_error_is_structured` 在 LLM 阶段就失败，不需要 Blender。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_server.py -v`
Expected: ERROR（`No module named 'orchestrator.server'`）

- [ ] **Step 3: 实现 server.py**

Create `orchestrator/orchestrator/server.py`:

```python
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
```

- [ ] **Step 4: 实现 static/index.html**

Create `orchestrator/orchestrator/static/index.html`:

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>ex-co-model</title>
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #16181d; color: #ddd; display: flex; height: 100vh; }
  #viewport { flex: 1; }
  #side { width: 340px; padding: 12px; display: flex; flex-direction: column; gap: 8px; border-left: 1px solid #333; }
  textarea { width: 100%; height: 80px; background: #222; color: #ddd; border: 1px solid #444; box-sizing: border-box; }
  button { padding: 8px; background: #3a6; color: #fff; border: 0; cursor: pointer; }
  button:disabled { background: #555; cursor: wait; }
  #status { font-size: 13px; color: #9b9; min-height: 18px; white-space: pre-wrap; }
  #tree { flex: 1; overflow: auto; background: #111; padding: 8px; font-size: 11px; }
  h3 { margin: 4px 0; font-size: 13px; color: #888; }
</style>
</head>
<body>
<div id="viewport"></div>
<div id="side">
  <h3>指令</h3>
  <textarea id="instruction" placeholder="例：一艘太空护卫舰，船尾装两个引擎喷口"></textarea>
  <button id="go">应用</button>
  <div id="status"></div>
  <h3>OpTree</h3>
  <pre id="tree">(empty)</pre>
</div>
<script type="importmap">
{"imports": {"three": "https://unpkg.com/three@0.160.0/build/three.module.js",
             "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"}}
</script>
<script type="module">
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const el = document.getElementById("viewport");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x2a2e35);
const camera = new THREE.PerspectiveCamera(50, el.clientWidth / el.clientHeight, 0.1, 5000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(el.clientWidth, el.clientHeight);
el.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(30, -30, 40);
scene.add(key);
scene.add(new THREE.GridHelper(100, 20, 0x444444, 0x333333));

let current = null;
function frame(obj) {
  const box = new THREE.Box3().setFromObject(obj);
  const size = box.getSize(new THREE.Vector3()).length() || 10;
  const center = box.getCenter(new THREE.Vector3());
  camera.position.set(center.x + size * 0.7, center.y - size * 0.7, center.z + size * 0.5);
  controls.target.copy(center);
  controls.update();
}
function loadModel() {
  new GLTFLoader().load("/model.glb?t=" + Date.now(), (g) => {
    if (current) scene.remove(current);
    current = g.scene;
    scene.add(current);
    frame(current);
  }, undefined, () => {});
}
async function refreshState() {
  const s = await (await fetch("/api/state")).json();
  document.getElementById("tree").textContent =
    s.tree ? JSON.stringify(s.tree, null, 1) : "(empty)";
}
document.getElementById("go").onclick = async () => {
  const btn = document.getElementById("go");
  const status = document.getElementById("status");
  const instruction = document.getElementById("instruction").value.trim();
  if (!instruction) return;
  btn.disabled = true; status.textContent = "AI 建模中…（首次构建可能要一两分钟）";
  try {
    const r = await (await fetch("/api/apply", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    })).json();
    if (r.ok) {
      status.textContent = `完成（${r.rounds} 轮，${r.nodes} 节点）`;
      await refreshState();
      loadModel();
    } else {
      status.textContent = "失败：" + r.error;
    }
  } catch (e) {
    status.textContent = "请求失败：" + e;
  }
  btn.disabled = false;
};
refreshState();
loadModel();
(function loop() { requestAnimationFrame(loop); renderer.render(scene, camera); })();
</script>
</body>
</html>
```

Modify `orchestrator/pyproject.toml`，在 `[tool.setuptools.packages.find]` 后加：

```toml
[tool.setuptools.package-data]
orchestrator = ["static/*"]
```

然后重装：`cd orchestrator && ../kernel/.venv/bin/pip install -e ".[dev]"`

Modify `orchestrator/orchestrator/cli.py`：
- `sub.add_parser("serve", parents=[common], help="start the local web ui")`，并给 serve 加 `--port`（type=int, default=8787）
- import 区加 `from orchestrator.server import serve as serve_ui`
- 分支：

```python
        elif args.cmd == "serve":
            serve_ui(args.session, args.workdir,
                     args.parts if args.parts.exists() else None,
                     llm_factory=MoonshotClient, port=args.port)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest -v`
Expected: 全部 passed（新增 4，其中 1 个 blender-gated）

- [ ] **Step 6: 手动冒烟（计入验收）**

```bash
cd /Users/breannalinlin/code/Github/ex-co-model && kernel/.venv/bin/orchestrator serve --port 8787
```

浏览器打开 `http://127.0.0.1:8787`：能看到现有护卫舰模型、OpTree 面板、指令框。输入一条修改指令提交，模型和树刷新。

- [ ] **Step 7: Commit**

```bash
git add orchestrator/
git commit -m "feat(orchestrator): local web ui with three.js viewport"
```

---

### Task 5: README + 收尾回归

**Files:**
- Modify: `orchestrator/README.md`
- Modify: `README.md`（根）

- [ ] **Step 1: 更新文档**

`orchestrator/README.md` 使用段加：

```bash
orchestrator preview                          # 构建并渲染预览 PNG（.exco/build/out/preview.png）
orchestrator apply "..." --check              # 带 VLM 自检（渲染图 vs 意图，不像自动重试 ≤2 轮）
orchestrator serve --port 8787                # 本地 Web UI：3D 视口 + 指令 + OpTree
```

设计要点段加一条：

```
- VLM 自检是尽力而为：模型不支持图片输入时打印 warning 跳过，不阻断主流程
- UI 是本地 Web 应用（stdlib HTTP + Three.js CDN），非 Electron/Tauri——零新 Python 依赖
```

根 `README.md` 追加一行 `- `orchestrator/` 含本地 Web UI（`orchestrator serve`）`。

- [ ] **Step 2: 全量最终回归**

```bash
cd kernel && .venv/bin/pytest -v
cd ../orchestrator && ../kernel/.venv/bin/pytest -v
```

Expected: kernel 48 passed；orchestrator 49 passed（37 + Task2 的 3 + Task3 的 5 + Task4 的 4）。全部 blender-gated 真实执行。

- [ ] **Step 3: Commit**

```bash
git add orchestrator/README.md README.md
git commit -m "docs(orchestrator): preview, self-check and web ui usage"
```

---

## 真实端到端验收（手动）

```bash
cd /Users/breannalinlin/code/Github/ex-co-model
kernel/.venv/bin/orchestrator apply "一艘太空护卫舰，船尾装两个引擎喷口" --check
kernel/.venv/bin/orchestrator serve --port 8787   # 浏览器验证 UI
```

验收标准：
1. `--check` 流程：渲染图被送往视觉模型；若模型不支持图片输入，打印 warning 但 apply 结果不受影响
2. Web UI 能看到模型、树、指令往返

## 后续（spec 之外或 v1.1）

- 圈选标注（viewport 点击 → 位置提示注入 prompt）
- 生成 worker（有机形状 `generate_organic`）
- 部件库扩充（手工精模）
- OpTree 可视化编辑
