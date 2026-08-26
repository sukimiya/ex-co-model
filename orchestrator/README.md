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
