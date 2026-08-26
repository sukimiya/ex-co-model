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
orchestrator apply "在船尾装两个引擎喷口"     # 若 ./parts 存在，部件列表自动注入 prompt
orchestrator show                          # 查看当前 OpTree
orchestrator build                         # 构建 FBX（.exco/build/out/）
orchestrator build --parts ./parts         # attach_part 需要部件库（默认 ./parts）
orchestrator preview                          # 构建并渲染预览 PNG（.exco/build/out/preview.png）
orchestrator apply "..." --check              # 带 VLM 自检（渲染图 vs 意图，不像自动重试 ≤2 轮）
orchestrator serve --port 8787                # 本地 Web UI：3D 视口 + 指令 + OpTree
```

会话默认存 `.exco/session.json`（文件本身就是 OpTree JSON）。

## 设计要点

- LLM 输出完整 OpTree（非 diff），由 `OpTree.model_validate` + `topo_order` 做确定性校验
- 校验失败把结构化错误回喂给 LLM 重试，最多 3 轮；超过向用户报错——AI 的失败不呈现为坏模型
- 测试不发起真实网络请求（FakeLLMClient / monkeypatch）
- VLM 自检是尽力而为：模型不支持图片输入时打印 warning 跳过，不阻断主流程
- UI 是本地 Web 应用（stdlib HTTP + Three.js CDN），非 Electron/Tauri——零新 Python 依赖
