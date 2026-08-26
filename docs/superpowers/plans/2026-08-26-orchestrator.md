# 编排服务（LLM → OpTree）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现编排服务：用户输入自然语言指令 → LLM（Moonshot/Kimi）产出 OpTree → schema+DAG 校验 → 失败回喂重试（≤3 轮）→ 更新会话 → 可调用内核构建 FBX。

**Architecture:** 新顶层包 `orchestrator/`（依赖已有 `kernel/optree`）。`llm.py`（LLMClient 协议 + MoonshotClient + FakeLLMClient）→ `prompts.py`（系统提示 + 消息构建）→ `core.py`（Orchestrator：校验重试循环）→ `session.py`（当前树的持久化）→ `cli.py`（`apply`/`build`/`show` 三个子命令）。

**Tech Stack:** Python ≥3.11、openai SDK ≥1.0（Moonshot 为 OpenAI 兼容 API）、pytest、已有 optree 包。

**Spec:** `docs/superpowers/specs/2026-08-25-ex-co-model-design.md`（覆盖第 4 节"编排服务"与第 7 节错误处理原则的 LLM 侧）

## 与 spec 的两处有意偏差（已决策）

1. **LLM 输出完整 OpTree，而非 JSON diff。** spec 第 4 节写的是"OpTree diff"。v1 改为输出完整树：树只有几十行，全量输出更简单、更不容易出错；diff 语义（节点重命名、移动引用）出错成本高。spec 的核心约束——"LLM 只碰 OpTree 不碰 mesh"——不受影响。
2. **VLM 自检闭环（渲染图对比）不在本计划。** 它依赖渲染管线和 UI 预览，归入计划 4。本计划的"校验"是确定性的：schema 校验 + 拓扑/环检查 + 几何预检（输入引用存在性已由 schema 保证）。

## Global Constraints

- Python ≥ 3.11；新依赖只允许 `openai>=1.0`；kernel 包保持零新增依赖
- Moonshot 接入参数全部走环境变量：`MOONSHOT_API_KEY`（必需）、`MOONSHOT_MODEL`（默认 `kimi-k2-0711-preview`）、`MOONSHOT_BASE_URL`（默认 `https://api.moonshot.ai/v1`）
- 所有单元测试不得发起真实网络请求（用 FakeLLMClient / monkeypatch）
- LLM 输出必须为完整 OpTree JSON（`{"nodes": {...}}`），校验规则与 kernel 完全一致（`OpTree.model_validate` + `topo_order`）
- 校验失败回喂上限 3 轮，超过抛 `OrchestratorError`，向用户呈现结构化错误——AI 的失败不能呈现为坏模型
- 代码标识符与注释用英文；commit message 用英文 conventional commits
- 所有代码在 `orchestrator/` 子目录下，测试在 `orchestrator/tests/`
- TDD：先写失败测试，再写最小实现，每个 Task 结束必须 commit

---

### Task 1: 脚手架 + LLM 客户端（Moonshot + Fake）

**Files:**
- Create: `orchestrator/pyproject.toml`
- Create: `orchestrator/orchestrator/__init__.py`
- Create: `orchestrator/orchestrator/errors.py`
- Create: `orchestrator/orchestrator/llm.py`
- Test: `orchestrator/tests/__init__.py`（空文件）
- Test: `orchestrator/tests/test_llm.py`

**Interfaces:**
- Consumes: 无（不依赖 kernel）
- Produces:
  - `orchestrator.errors.OrchestratorError`
  - `orchestrator.llm.LLMClient`（Protocol：`complete(messages: list[dict]) -> str`）
  - `orchestrator.llm.MoonshotClient(api_key=None, base_url=None, model=None)`（缺 key 抛 `OrchestratorError`）
  - `orchestrator.llm.FakeLLMClient(responses: list[str])`（`.calls: list[list[dict]]` 记录调用；响应用完后抛 `AssertionError`）

- [ ] **Step 1: 创建脚手架与虚拟环境**

Create `orchestrator/pyproject.toml`:

```toml
[project]
name = "orchestrator"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["openai>=1.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["orchestrator*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

注意：orchestrator 运行依赖本地 kernel 包，先 `pip install -e ../kernel`（pyproject 里不能写 "optree"——PyPI 上有同名无关包）。

Create `orchestrator/orchestrator/__init__.py`（空文件）和 `orchestrator/tests/__init__.py`（空文件）。

Run（复用 kernel 的 venv，optree 已装；orchestrator 也装进同一个 venv）:

```bash
cd orchestrator && ../kernel/.venv/bin/pip install -e ".[dev]"
```

Expected: 安装成功（openai 及其依赖被装入）。

- [ ] **Step 2: 写失败测试**

Create `orchestrator/tests/test_llm.py`:

```python
import pytest

from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient, MoonshotClient


def test_moonshot_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    with pytest.raises(OrchestratorError, match="MOONSHOT_API_KEY"):
        MoonshotClient()


def test_moonshot_client_calls_openai_compatible_api(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            class Msg:
                content = '{"nodes": {}}'
            class Choice:
                message = Msg()
            class Resp:
                choices = [Choice()]
            return Resp()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("orchestrator.llm.OpenAI", FakeOpenAI)
    client = MoonshotClient(api_key="sk-test", model="kimi-k2-0711-preview")
    out = client.complete([{"role": "user", "content": "hi"}])
    assert out == '{"nodes": {}}'
    assert captured["model"] == "kimi-k2-0711-preview"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_moonshot_client_reads_env(monkeypatch):
    monkeypatch.setattr("orchestrator.llm.OpenAI", lambda api_key, base_url: None)
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-env")
    monkeypatch.delenv("MOONSHOT_MODEL", raising=False)
    monkeypatch.delenv("MOONSHOT_BASE_URL", raising=False)
    client = MoonshotClient()
    assert client.api_key == "sk-env"
    assert client.model == "kimi-k2-0711-preview"


def test_fake_llm_client_queues_and_records():
    fake = FakeLLMClient(["resp1", "resp2"])
    assert fake.complete([{"role": "user", "content": "a"}]) == "resp1"
    assert fake.complete([{"role": "user", "content": "b"}]) == "resp2"
    assert len(fake.calls) == 2
    with pytest.raises(AssertionError, match="ran out"):
        fake.complete([])
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest -v`
Expected: 全部 ERROR/FAIL（`ModuleNotFoundError: No module named 'orchestrator.errors'`）

- [ ] **Step 4: 实现 errors.py 与 llm.py**

Create `orchestrator/orchestrator/errors.py`:

```python
class OrchestratorError(Exception):
    """Base error for orchestration failures (config, llm, validation)."""
```

Create `orchestrator/orchestrator/llm.py`:

```python
from __future__ import annotations

import os
from typing import Protocol

from openai import OpenAI

from orchestrator.errors import OrchestratorError

DEFAULT_MODEL = "kimi-k2-0711-preview"
DEFAULT_BASE_URL = "https://api.moonshot.ai/v1"


class LLMClient(Protocol):
    """Anything that can complete a chat message list and return raw text."""

    def complete(self, messages: list[dict]) -> str: ...


class MoonshotClient:
    """Moonshot/Kimi client via the OpenAI-compatible API."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None):
        self.api_key = api_key or os.environ.get("MOONSHOT_API_KEY")
        if not self.api_key:
            raise OrchestratorError(
                "MOONSHOT_API_KEY not set; export it before using the orchestrator"
            )
        self.model = model or os.environ.get("MOONSHOT_MODEL", DEFAULT_MODEL)
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=base_url or os.environ.get("MOONSHOT_BASE_URL", DEFAULT_BASE_URL),
        )

    def complete(self, messages: list[dict]) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content


class FakeLLMClient:
    """Test double: returns queued responses in order and records calls."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("FakeLLMClient ran out of queued responses")
        return self.responses.pop(0)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add orchestrator/
git commit -m "feat(orchestrator): llm client protocol with moonshot and fake"
```

---

### Task 2: Prompt 构建

**Files:**
- Create: `orchestrator/orchestrator/prompts.py`
- Test: `orchestrator/tests/test_prompts.py`

**Interfaces:**
- Consumes: `optree.schema.OpTree`（kernel，Task 1 已装入 venv）
- Produces:
  - `orchestrator.prompts.SYSTEM_PROMPT: str`（含 OpTree v1 全部节点类型的文档与输出契约）
  - `orchestrator.prompts.build_messages(instruction: str, current_tree: OpTree | None) -> list[dict]`（system + 单条 user 消息）
  - `orchestrator.prompts.feedback_message(error: str) -> dict`（回喂校验错误的 user 消息）

- [ ] **Step 1: 写失败测试**

Create `orchestrator/tests/test_prompts.py`:

```python
from optree.schema import OpTree

from orchestrator.prompts import SYSTEM_PROMPT, build_messages, feedback_message


def sample_tree() -> OpTree:
    return OpTree.model_validate({
        "nodes": {
            "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
            "out": {"op": "export_fbx", "inputs": ["hull"], "params": {"filename": "ship.fbx"}},
        }
    })


def test_system_prompt_documents_all_v1_ops():
    for op in ["primitive", "bevel", "boolean_subtract", "scale_to", "export_fbx"]:
        assert op in SYSTEM_PROMPT
    assert "json" in SYSTEM_PROMPT.lower()


def test_build_messages_without_tree_is_create_mode():
    msgs = build_messages("一艘双引擎护卫舰", None)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "一艘双引擎护卫舰" in msgs[1]["content"]
    assert "Current OpTree" not in msgs[1]["content"]


def test_build_messages_with_tree_embeds_current_json():
    msgs = build_messages("把船加长到40米", sample_tree())
    user = msgs[1]["content"]
    assert "Current OpTree" in user
    assert '"hull"' in user
    assert "把船加长到40米" in user


def test_feedback_message_wraps_error():
    msg = feedback_message("node 'a' references unknown node 'zz'")
    assert msg["role"] == "user"
    assert "references unknown node" in msg["content"]
    assert "corrected" in msg["content"].lower()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_prompts.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'orchestrator.prompts'`）

- [ ] **Step 3: 实现 prompts.py**

Create `orchestrator/orchestrator/prompts.py`:

```python
import json

from optree.schema import OpTree

SYSTEM_PROMPT = """\
You are the modeling planner of ex-co-model, an AI-driven parametric 3D modeling \
tool for game assets. You never touch meshes directly. You read and write ONLY \
the OpTree: a JSON document describing modeling operations as a DAG.

Output contract:
- Respond with ONE json object: {"nodes": {<name>: <node>, ...}}. No prose.
- Every node: {"op": <op>, "inputs": [<node names>], "params": {...}}; omit "params" entirely for boolean_subtract (it has none).
- inputs reference other node names; every reference must exist; no cycles.
- Units are meters. Keep the final export_fbx node pointing at the final geometry.

Node types (v1):
- primitive: no inputs. params: type ("box"|"cylinder"), size [x,y,z] (box, full \
extents), radius/depth/vertices (cylinder), location [x,y,z].
- bevel: inputs [src]. params: width, segments.
- boolean_subtract: inputs [target, cutter]. Cut a slot/hole out of target.
- scale_to: inputs [src]. params: length_m (>0). Uniformly scales so the longest \
axis equals length_m.
- export_fbx: inputs [src]. params: filename (plain basename ending in .fbx).

When modifying an existing tree, change only what the instruction requires and \
keep every unrelated node byte-identical (names, params, structure).\
"""


def build_messages(instruction: str, current_tree: OpTree | None) -> list[dict]:
    user = ""
    if current_tree is not None:
        tree_json = json.dumps(
            {"nodes": {k: v.model_dump(exclude_defaults=True)
                       for k, v in current_tree.nodes.items()}},
            indent=2,
        )
        user += f"Current OpTree:\n```json\n{tree_json}\n```\n\n"
    user += f"Instruction: {instruction}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def feedback_message(error: str) -> dict:
    """User-role message feeding a validation error back to the LLM."""
    return {
        "role": "user",
        "content": (
            f"The OpTree you produced is invalid. Error: {error}\n"
            "Return a corrected complete OpTree json object only."
        ),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_prompts.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator/prompts.py orchestrator/tests/test_prompts.py
git commit -m "feat(orchestrator): prompt builder with optree v1 schema docs"
```

---

### Task 3: 校验重试循环（Orchestrator 核心）

**Files:**
- Create: `orchestrator/orchestrator/core.py`
- Test: `orchestrator/tests/test_core.py`

**Interfaces:**
- Consumes: `LLMClient`/`FakeLLMClient`（Task 1）、`build_messages`/`feedback_message`（Task 2）、`optree.schema.OpTree`、`optree.graph.topo_order`、`optree.errors.CycleError`、`orchestrator.errors.OrchestratorError`
- Produces:
  - `orchestrator.core.ApplyResult`（dataclass：`.tree: OpTree`、`.rounds: int`）
  - `orchestrator.core.run_apply(llm: LLMClient, instruction: str, current_tree: OpTree | None, max_rounds: int = 3) -> ApplyResult`——纯函数，不做持久化（持久化归 Task 4）

- [ ] **Step 1: 写失败测试**

Create `orchestrator/tests/test_core.py`:

```python
import json

import pytest

from orchestrator.core import run_apply
from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient

VALID_TREE = json.dumps({
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"], "params": {"filename": "ship.fbx"}},
    }
})

INVALID_REF_TREE = json.dumps({
    "nodes": {
        "out": {"op": "export_fbx", "inputs": ["ghost"], "params": {"filename": "ship.fbx"}},
    }
})

CYCLE_TREE = json.dumps({
    "nodes": {
        "a": {"op": "bevel", "inputs": ["b"]},
        "b": {"op": "bevel", "inputs": ["a"]},
    }
})


def test_valid_response_first_try():
    llm = FakeLLMClient([VALID_TREE])
    result = run_apply(llm, "一艘护卫舰", None)
    assert result.rounds == 1
    assert set(result.tree.nodes) == {"hull", "out"}


def test_invalid_json_then_valid_retries():
    llm = FakeLLMClient(["not json at all", VALID_TREE])
    result = run_apply(llm, "一艘护卫舰", None)
    assert result.rounds == 2
    # second call must carry the error feedback
    second_call = llm.calls[1]
    assert any("invalid" in m["content"].lower() for m in second_call if m["role"] == "user")


def test_schema_error_is_fed_back():
    llm = FakeLLMClient([INVALID_REF_TREE, VALID_TREE])
    result = run_apply(llm, "一艘护卫舰", None)
    assert result.rounds == 2
    feedback = llm.calls[1][-1]["content"]
    assert "unknown node" in feedback


def test_cycle_error_is_fed_back():
    llm = FakeLLMClient([CYCLE_TREE, VALID_TREE])
    result = run_apply(llm, "一艘护卫舰", None)
    assert result.rounds == 2
    assert "cycle" in llm.calls[1][-1]["content"]


def test_max_rounds_exceeded_raises():
    llm = FakeLLMClient([INVALID_REF_TREE] * 3)
    with pytest.raises(OrchestratorError, match="3 rounds"):
        run_apply(llm, "一艘护卫舰", None)


def test_current_tree_passed_to_messages():
    from optree.schema import OpTree
    current = OpTree.model_validate(json.loads(VALID_TREE))
    llm = FakeLLMClient([VALID_TREE])
    run_apply(llm, "加长到40米", current)
    assert '"hull"' in llm.calls[0][1]["content"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_core.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'orchestrator.core'`）

- [ ] **Step 3: 实现 core.py**

Create `orchestrator/orchestrator/core.py`:

```python
import json
from dataclasses import dataclass

from pydantic import ValidationError

from optree.errors import CycleError
from optree.graph import topo_order
from optree.schema import OpTree

from orchestrator.errors import OrchestratorError
from orchestrator.llm import LLMClient
from orchestrator.prompts import build_messages, feedback_message


@dataclass
class ApplyResult:
    tree: OpTree
    rounds: int


def _validate(raw: str) -> OpTree:
    """Parse + schema-validate + dag-check an LLM response. Raises on failure."""
    tree = OpTree.model_validate(json.loads(raw))
    topo_order(tree)  # raises CycleError
    return tree


def run_apply(llm: LLMClient, instruction: str, current_tree: OpTree | None,
              max_rounds: int = 3) -> ApplyResult:
    """Ask the LLM for an OpTree; feed validation errors back up to max_rounds."""
    messages = build_messages(instruction, current_tree)
    last_error: str | None = None
    for round_no in range(1, max_rounds + 1):
        raw = llm.complete(messages)
        try:
            tree = _validate(raw)
        except (json.JSONDecodeError, ValidationError, CycleError) as e:
            last_error = str(e)
            messages.append({"role": "assistant", "content": raw})
            messages.append(feedback_message(last_error))
            continue
        return ApplyResult(tree=tree, rounds=round_no)
    raise OrchestratorError(
        f"llm failed to produce a valid optree after {max_rounds} rounds: {last_error}"
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_core.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator/core.py orchestrator/tests/test_core.py
git commit -m "feat(orchestrator): validation retry loop with llm feedback"
```

---

### Task 4: 会话持久化

**Files:**
- Create: `orchestrator/orchestrator/session.py`
- Test: `orchestrator/tests/test_session.py`

**Interfaces:**
- Consumes: `optree.schema.OpTree` / `load_optree`、Task 3 的 `run_apply`
- Produces:
  - `orchestrator.session.Session(path)`——`.tree: OpTree | None`（初始化时若文件存在则加载）；`.apply(llm, instruction) -> ApplyResult`（调 `run_apply` 并持久化新树）
  - 会话文件就是 OpTree JSON 本体（`{"nodes": {...}}`），非包装格式

- [ ] **Step 1: 写失败测试**

Create `orchestrator/tests/test_session.py`:

```python
import json

from orchestrator.llm import FakeLLMClient
from orchestrator.session import Session

VALID_TREE = {
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"], "params": {"filename": "ship.fbx"}},
    }
}


def test_new_session_has_no_tree(tmp_path):
    assert Session(tmp_path / "s.json").tree is None


def test_apply_persists_tree(tmp_path):
    path = tmp_path / "s.json"
    session = Session(path)
    llm = FakeLLMClient([json.dumps(VALID_TREE)])
    result = session.apply(llm, "一艘护卫舰")
    assert result.rounds == 1
    assert json.loads(path.read_text())["nodes"]["hull"]["op"] == "primitive"


def test_session_reloads_persisted_tree(tmp_path):
    path = tmp_path / "s.json"
    Session(path).apply(FakeLLMClient([json.dumps(VALID_TREE)]), "一艘护卫舰")
    reloaded = Session(path)
    assert reloaded.tree is not None
    assert set(reloaded.tree.nodes) == {"hull", "out"}


def test_second_apply_sees_existing_tree(tmp_path):
    path = tmp_path / "s.json"
    session = Session(path)
    session.apply(FakeLLMClient([json.dumps(VALID_TREE)]), "一艘护卫舰")
    llm = FakeLLMClient([json.dumps(VALID_TREE)])
    session.apply(llm, "加长到40米")
    assert '"hull"' in llm.calls[0][1]["content"]  # current tree embedded
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_session.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'orchestrator.session'`）

- [ ] **Step 3: 实现 session.py**

Create `orchestrator/orchestrator/session.py`:

```python
import json
from pathlib import Path

from optree.schema import OpTree

from orchestrator.core import ApplyResult, run_apply
from orchestrator.llm import LLMClient


class Session:
    """One asset under editing. The session file IS the OpTree json."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.tree: OpTree | None = None
        if self.path.exists():
            self.tree = OpTree.model_validate(
                json.loads(self.path.read_text(encoding="utf-8"))
            )

    def apply(self, llm: LLMClient, instruction: str) -> ApplyResult:
        result = run_apply(llm, instruction, self.tree)
        self.tree = result.tree
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"nodes": {k: v.model_dump(exclude_defaults=True)
                           for k, v in self.tree.nodes.items()}},
                indent=2,
            ),
            encoding="utf-8",
        )
        return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_session.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator/session.py orchestrator/tests/test_session.py
git commit -m "feat(orchestrator): session persistence for current optree"
```

---

### Task 5: CLI + README + 收尾回归

**Files:**
- Create: `orchestrator/orchestrator/cli.py`
- Create: `orchestrator/README.md`
- Modify: `README.md`（项目根，补一行指向 orchestrator）
- Test: `orchestrator/tests/test_cli.py`

**Interfaces:**
- Consumes: 全部前置任务 + `optree.engine.build`
- Produces: `orchestrator` 命令，子命令：
  - `orchestrator apply "<instruction>" [--session PATH]`（默认 `.exco/session.json`）：LLM 应用指令，持久化，打印轮数与节点数
  - `orchestrator build [--session PATH] [--workdir DIR]`（默认 `.exco/build`）：对当前树跑内核构建，打印 FBX 路径
  - `orchestrator show [--session PATH]`：打印当前树 JSON
- `orchestrator.cli.main(argv=None, llm=None) -> int`（`llm` 参数供测试注入；为 None 时构造 `MoonshotClient`）

- [ ] **Step 1: 写失败测试**

Create `orchestrator/tests/test_cli.py`:

```python
import json

import pytest

from optree.schema import OpTree

from orchestrator.cli import main
from orchestrator.errors import OrchestratorError
from orchestrator.llm import FakeLLMClient
from tests.conftest import requires_blender

VALID_TREE = json.dumps({
    "nodes": {
        "hull": {"op": "primitive", "params": {"type": "box", "size": [10, 3, 2]}},
        "out": {"op": "export_fbx", "inputs": ["hull"], "params": {"filename": "ship.fbx"}},
    }
})


def test_apply_creates_session(tmp_path, capsys):
    session = tmp_path / "s.json"
    fake = FakeLLMClient([VALID_TREE])
    assert main(["apply", "一艘护卫舰", "--session", str(session)], llm=fake) == 0
    out = capsys.readouterr().out
    assert "round 1" in out or "rounds=1" in out
    assert session.exists()


def test_apply_llm_failure_exit_1(tmp_path, capsys):
    fake = FakeLLMClient(["garbage"] * 3)
    assert main(["apply", "x", "--session", str(tmp_path / "s.json")], llm=fake) == 1
    assert "error" in capsys.readouterr().err


def test_show_without_session_exit_1(tmp_path, capsys):
    assert main(["show", "--session", str(tmp_path / "nope.json")]) == 1


def test_show_prints_tree(tmp_path, capsys):
    session = tmp_path / "s.json"
    session.write_text(VALID_TREE, encoding="utf-8")
    assert main(["show", "--session", str(session)]) == 0
    assert '"hull"' in capsys.readouterr().out


@requires_blender
def test_build_produces_fbx(tmp_path, capsys):
    session = tmp_path / "s.json"
    session.write_text(VALID_TREE, encoding="utf-8")
    assert main(["build", "--session", str(session),
                 "--workdir", str(tmp_path / "build")]) == 0
    assert "ship.fbx" in capsys.readouterr().out
    assert (tmp_path / "build" / "out" / "ship.fbx").exists()
```

Create `orchestrator/tests/conftest.py`（复用 kernel 的 requires_blender 定义，避免跨包导入 tests 包）:

```python
import shutil

import pytest

requires_blender = pytest.mark.skipif(
    shutil.which("blender") is None, reason="blender not on PATH"
)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest tests/test_cli.py -v`
Expected: ERROR（`ModuleNotFoundError: No module named 'orchestrator.cli'`）

- [ ] **Step 3: 实现 cli.py**

Create `orchestrator/orchestrator/cli.py`:

```python
import argparse
import json
import sys
from pathlib import Path

from optree.engine import build
from optree.errors import OpTreeError

from orchestrator.errors import OrchestratorError
from orchestrator.llm import LLMClient, MoonshotClient
from orchestrator.session import Session


def main(argv: list[str] | None = None, llm: LLMClient | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--session", type=Path, default=Path(".exco/session.json"))

    a = sub.add_parser("apply", parents=[common], help="apply a natural-language instruction")
    a.add_argument("instruction")
    b = sub.add_parser("build", parents=[common], help="build the current tree to fbx")
    b.add_argument("--workdir", type=Path, default=Path(".exco/build"))
    sub.add_parser("show", parents=[common], help="print the current tree")

    args = parser.parse_args(argv)
    session = Session(args.session)

    try:
        if args.cmd == "apply":
            client = llm if llm is not None else MoonshotClient()
            result = session.apply(client, args.instruction)
            print(f"applied in rounds={result.rounds}, nodes={len(result.tree.nodes)}")
        elif args.cmd == "build":
            if session.tree is None:
                print(f"error: no session tree at {args.session}", file=sys.stderr)
                return 1
            for p in build(session.tree, args.workdir).exports:
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
    except (OrchestratorError, OpTreeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

注意：`pyproject.toml`（Task 1）未注册 orchestrator 的 entry point，补一行。Modify `orchestrator/pyproject.toml`，在 `[project]` 之后加：

```toml
[project.scripts]
orchestrator = "orchestrator.cli:main"
```

然后重装使其生效：`cd orchestrator && ../kernel/.venv/bin/pip install -e ".[dev]"`

- [ ] **Step 4: 跑测试确认通过**

Run: `cd orchestrator && ../kernel/.venv/bin/pytest -v`
Expected: 全部 passed（blender-gated 的 `test_build_produces_fbx` 在有 Blender 的机器上真正执行）

- [ ] **Step 5: 写 orchestrator/README.md + 更新根 README**

Create `orchestrator/README.md`：

````markdown
# orchestrator

编排服务：自然语言指令 → LLM（Moonshot/Kimi）→ OpTree → 校验（schema + DAG）→ 失败回喂重试（≤3 轮）→ 调用内核构建 FBX。

## 环境

- Python ≥ 3.11；Blender ≥ 4.0（仅 `build` 子命令需要）
- `export MOONSHOT_API_KEY=...`（必需；可选 `MOONSHOT_MODEL`、`MOONSHOT_BASE_URL`）

## 安装与测试

```bash
cd orchestrator
../kernel/.venv/bin/pip install -e ".[dev]"   # 复用 kernel 的 venv
../kernel/.venv/bin/pytest
```

## 使用

```bash
orchestrator apply "一艘双引擎太空护卫舰，船身侧面开一个机库口"
orchestrator apply "全长改成40米"           # 修改当前会话的树
orchestrator show                          # 查看当前 OpTree
orchestrator build                         # 构建 FBX（.exco/build/out/）
```

会话默认存 `.exco/session.json`（文件本身就是 OpTree JSON）。

## 设计要点

- LLM 输出完整 OpTree（非 diff），由 `OpTree.model_validate` + `topo_order` 做确定性校验
- 校验失败把结构化错误回喂给 LLM 重试，最多 3 轮；超过向用户报错——AI 的失败不呈现为坏模型
- 测试不发起真实网络请求（FakeLLMClient / monkeypatch）
````

Modify 根 `README.md`：追加一行 `- `orchestrator/`：自然语言 → OpTree 编排服务，见 [orchestrator/README.md](orchestrator/README.md)`。

- [ ] **Step 6: 全量最终回归（两个包）**

```bash
cd kernel && .venv/bin/pytest -v
cd ../orchestrator && ../kernel/.venv/bin/pytest -v
```

Expected: kernel 34 passed；orchestrator 全部 passed（22 个非 blender 测试 + 1 个 blender-gated）

- [ ] **Step 7: Commit**

```bash
git add orchestrator/ README.md
git commit -m "feat(orchestrator): cli with apply/build/show and readme"
```

---

## 真实 LLM 端到端验证（手动，需 MOONSHOT_API_KEY，不计入测试）

```bash
export MOONSHOT_API_KEY=<your key>
cd orchestrator
../kernel/.venv/bin/orchestrator apply "一艘双引擎太空护卫舰"
../kernel/.venv/bin/orchestrator apply "全长改成40米，船身侧面开一个机库口"
../kernel/.venv/bin/orchestrator build
```

验收：第一条生成合法树；第二条只改相关节点（`scale_to` 参数 + 新增 boolean_subtract），导出 FBX 成功。

## 后续计划（不在本计划内）

- 计划 3：部件库（snap 接口 + `attach_part` 节点 + 首批精模）
- 计划 4：UI 壳 + 渲染管线 + VLM 自检闭环
