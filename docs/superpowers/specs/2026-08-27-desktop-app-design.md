# ex-co-model 桌面 App 设计（子项目 1）

日期：2026-08-27
状态：已确认（用户逐节过目）
关联：主 spec `2026-08-25-ex-co-model-design.md`

## 1. 背景与定位

MVP（v1.1 止）交付的是本地 web 工具：Python orchestrator + Blender headless + stdlib server + three.js。本文档定义它的下一个形态：**可编译、可上架 Steam、与 excape-from-expanse 配套分发的桌面软件**。

产品定位：**游戏的 mod/UGC 工具**——玩家为 excape-from-expanse 造舰船资产。不是纯对话工具，而是**"拼装式编辑器 + AI 助手"**：

- **手动拼装（kitbash）**：玩家在 3D 视口里直接拖部件、摆位置、开槽、缩放。边界明确：**不做** Fusion 360 式的顶点/曲线/草图编辑——玩家不碰曲线、不手动对齐边缘（形态上更接近 Space Engineers / KSP 的搭建，而非 CAD）
- **自动对齐**：部件声明吸附点/接口，拖动时自动吸附到最近的面/边缘/接口（确定性几何计算，不依赖 AI）
- **外部模型导入**：玩家下载的 GLB/FBX 归一化尺寸/朝向后作为一种"部件"进库，参与拼装（导入 mesh 不可参数化编辑，但可摆放/缩放/开槽）
- **AI 演算补形（核心差异化）**：SE/KSP 里"功能区搭好了，外形糊不出来"是玩家最大痛点。本工具的闭环是——**玩家摆功能区（手动+吸附）→ AI 以这些部件为锚点演算船体外形（OpTree 生成包裹几何）→ 玩家局部调整或下指令 → 风格库精修 → 导出**。玩家负责 idea，AI 负责把粗糙拼装演算成可游戏的精美模型
- **风格库**：玩家选中面/区域指定风格（如"军用"），AI 从风格库（装饰件库 + 风格化 prompt）生成 greeble 精修——面板线、散热口、装甲板，落到 OpTree 就是 attach_part + boolean 序列
- **手动与 AI 统一**：每一次手动拖拽也生成 OpTree 节点。手动摆的部件 LLM 看得懂、改得动；撤销/重做 = DAG 重放；缓存增量重算原样复用

### 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 目标用户 | 玩家（mod/UGC），非专业开发者 |
| 资产进游戏 | 先 A 后 B：A = GLB + 游戏侧 glTFast 运行时加载 + Steam Workshop 分发；B = AssetBundle 管线（远期）。架构上导出格式留抽象层 |
| LLM 架构 | 纯 BYOK：玩家在设置里填自己的 OpenAI 兼容 API key。不架代理服务器 |
| 目标平台 | Windows + macOS，各平台本机构建（Windows 包在 Windows 机器上出） |
| App 壳 | pywebview + PyInstaller（onedir），复用现有 Python 代码与 three.js UI |
| Blender | 官方 portable 包捆绑进安装包（约 350MB/平台） |

### 范围拆分（独立子项目，本文档只管 1）

1. **ex-co-model 桌面 app**（本仓库，本文档）✅ —— 打包分发层，壳与功能解耦
2. **交互拼装编辑器**（本仓库，后续 spec）—— 视口直接操作 + 吸附对齐 + 手动操作映射为 OpTree 节点 + AI 演算补形
3. **外部模型导入**（本仓库，后续 spec）—— GLB/FBX 归一化进部件库
4. **风格库**（本仓库，后续 spec）—— greeble 装饰件库 + 区域风格化
5. **游戏侧 GLB 运行时加载**（excape-from-expanse 仓库，另行立 spec）
6. **Steam Workshop 上传**（后置；MVP 先导出 GLB 到目录，玩家手动传 Workshop）

## 2. 架构

复用为主：kernel（optree）、orchestrator（llm/core/session/check/pipeline/server）、parts/、three.js UI **全部不动**。新增薄壳 `app/` 包：

```
app/
  main.py        # 入口：后台线程起 orchestrator server（127.0.0.1 随机端口），
                 # pywebview 开原生窗口指向它；关窗即退出
  paths.py       # 用户数据目录解析（见下）
```

**用户数据目录**：现有 session/build 缓存在 `./.exco/`（跟工作目录走）。安装后的 app 没有工作目录概念，改为平台标准位置：

- Windows: `%APPDATA%/ex-co-model/`
- macOS: `~/Library/Application Support/ex-co-model/`
- CLI 行为不变（默认仍 `./.exco`）；app 模式通过启动参数/环境变量传入数据目录

**数据流**：与现状一致——用户在窗口里输入指令 → orchestrator → LLM（玩家自己的 key）→ OpTree → Blender headless 构建 → GLB/FBX/PNG 回显。唯一的网络出口是玩家配置的 LLM endpoint。

## 3. Blender 捆绑

`blender_session` 的 Blender 查找顺序改为：

1. `EXCO_BLENDER` 环境变量（显式指定）
2. app 包内捆绑的 portable Blender（`app/blender/` 子目录）
3. 系统 PATH（开发机现状）

Blender 用官方 portable zip 原样捆绑。以独立子进程（命令行）调用，属 GPL aggregate 分发，不传染自有代码；app 内需附 Blender GPL 文本与源码获取说明（上架标准工序，非法律意见，上架前再确认一次）。

启动时检测 Blender 可用性，找不到给明确报错与指引，不做自动下载。

## 4. BYOK 设置界面

Web UI 增加设置区（server 加 `/api/settings` GET/POST）：

- 三个字段：endpoint URL、API key、model name
- 预设 OpenAI 兼容端点一键填充（Kimi、OpenAI、DeepSeek）
- 存用户数据目录 `settings.json`（chmod 600），优先级高于仓库 `.env`
- `config.py` 的加载链扩展为：环境变量 > settings.json > .env
- key 未配置时 UI 引导到设置区，而不是报错退出

## 5. 打包与分发

- PyInstaller **onedir**（比 onefile 启动快、杀软误报少）
  - Windows：输出目录 + 捆绑 Blender 子目录
  - macOS：`.app` bundle + 捆绑 Blender
- 构建脚本：`scripts/build_app.sh`（macOS）/ `scripts/build_app.ps1`（Windows）。**不支持交叉编译**，各平台本机构建
- Steam 上传用 steampipe，windows/macos 两个 depot 分开
- 预估体积：约 450MB/平台（Python 运行时 ~100MB + Blender ~350MB）
- 代码签名 / 公证：上架前手动工序，不进本次范围

## 6. 错误处理

| 场景 | 行为 |
|---|---|
| Blender 缺失 | 启动检测，UI 给明确报错 + 指引 |
| LLM key 未配置 | UI 引导到设置区 |
| 构建失败/超时 | 沿用现有 300s 超时与错误透传，UI 可读提示 |

## 7. 测试

- 现有 127 个测试（kernel + orchestrator）全保留，不破坏
- 新增：数据目录解析（paths.py）、Blender 查找顺序、settings.json 加载链、app 入口 smoke（headless 环境跳过 webview 创建）
- 验收：打出的包在干净环境（无 Python、无 Blender、无 .env）跑通 设置 key → apply → preview → 导出 GLB

## 8. 不做（YAGNI，本子项目范围内）

- 交互拼装编辑器、外部模型导入、风格库（子项目 2/3/4，另立 spec）
- Steam Workshop 上传（子项目 6）
- 游戏侧运行时加载器（子项目 5）
- 多资产管理、资产库浏览
- 自动更新（交给 Steam）
- 代码签名/公证自动化
- LLM 代理服务器（已定 BYOK）

## 9. 验收标准

1. macOS 上 `scripts/build_app.sh` 产出 `.app`，双击运行，干净环境（无系统 Blender）完成一次完整建模并导出 GLB
2. Windows 机器上 `scripts/build_app.ps1` 产出等价包，同样跑通
3. 现有全部测试通过，CLI 工作流（`orchestrator apply/build/serve`）行为不变
