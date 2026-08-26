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
