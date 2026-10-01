---
name: psd2live-replace-layer-art
description: 替换 PSD2Live 已绑定工程中的身体、衣服等指定图层原画，保留图层身份、有效变形和动作。适用于从修复后的 PSD 更新局部素材，以及处理透明轮廓改变后的网格历史回放冲突；不用于整套重新导入或通用 PSD 绘画。
---

# PSD2Live 局部原画替换

目标是更新指定图层的像素，同时保留有效绑定和动作。不要把“导入成功”“结构有效”“画面正确”“动作正确”混为一谈。脚本接受只说明可以写这份副本；仍要用软件打开、看画面、看动作并原生保存。脚本拒绝时停下来，不要补零、截断或自行删除关键形。

## 先排除两个误判

- 两份磁盘 PSD 哈希相同，不能说明工程已经是精修版。当前画面以工程 HEAD 的图层贴图为准。内嵌 `source/original.psd` 只是导入时的源文件；之后的拆层和遮挡修复可能只在 HEAD 里。
- “重新分析 PSD”和 `asset psd` 会重建源图层，把这些修复和绑定丢掉。当前插件没有替换已绑定层像素的工具：`place` 只重定位已导入层，`add` 会新建层。版本变了就重新核对工具，不要凭名字猜测。

需要操作界面时，先读已安装的 computer-use skill，用它的窗口、截图和输入接口。文件对话框的注意点在 [存档与回放](references/archive-and-replay.md)。存档替换前先读该文档，确认本机格式仍相符。

## 下一次按这个顺序

1. 用原生界面把内存中的最新工程另存为基线。只复制磁盘文件可能漏掉未保存绑定。原工程和基线都保留。
2. 运行 `compare_layers.py`。选择器用 `工程ID或唯一名称=PSD名称或完整路径`，不要用会覆盖重名的字典。`significant_pixels` 为 0 的层不换。`invisible_rgb_only_pixels` 是两侧都几乎全透明时剩下的 RGB 差值，不是原画差异。alpha 相同而可见 RGB 只有轻微数值差时，先视为转换误差，不扩大范围。脚本把 alpha 差值大于 8，或两侧 alpha 都大于 8 且 RGB 差值大于 8，算作显著变化。
3. 新的可见像素越过旧 raster 框时，对比和替换都会拒绝。没有几何迁移脚本，停止并说明，不要改旧框硬套。替换时保留图层 ID、原框、位置、层序、混合和通道。
4. 被替换层的 alpha 有变化，且日志里还有网格 `positionDeltas` 时，先运行 `inspect_journal.py --check`。只有 `accepted` 为 true，才把同一个 `网格ID:参数` 传给 `--clean-obsolete-mesh`。关键值以这次输出为准，不沿用别的工程。
5. `replace_layers.py` 只写不存在的新文件。`non_pixel_changes` 只能为空，或只有刚刚接受的那组日志。`unchanged_rig_fields` 必须仍包含 `physics`、`warps`、`swings`、`parameters`。没清理时，`remaining_mesh_delta_targets` 里的网格要在打开前复核。
6. 用原生界面打开新副本。若顶点数量不匹配，关闭它，回到第 4 步另写一个新文件。不要修改失败副本，也不要把它当结果。
7. 检查合成画面和衣摆、胯部等接缝，以及受影响参数的端点和中间值。图层独显不能代替全模型遮挡检查。
8. 原生保存后再打开。外部修订号不是软件的原生修订号，未保存标记要靠这次保存消除。确认历史、资源和有效动作仍在。

## 脚本

脚本在 `scripts/`，依赖 Python 3、`Pillow`、`numpy`、`psd-tools`。从该目录运行，或把该目录加入 `PYTHONPATH`。`layer_archive.py` 是共享实现；对比、检查和替换必须调用它，不要另写一套判断。

```powershell
python scripts/compare_layers.py --project "baseline.psd2live" --psd "refined.psd" --layer "layer-id=group/layer" --output "comparison.png"
python scripts/inspect_journal.py --project "baseline.psd2live" --check "MeshId:ParameterId"
python scripts/replace_layers.py --project "baseline.psd2live" --psd "refined.psd" --layer "layer-id=group/layer" --clean-obsolete-mesh "MeshId:ParameterId" --output "candidate.psd2live"
```

`--clean-obsolete-mesh` 可省略。检查脚本和替换脚本用同一条件：该网格事件正好是三次 `set` 加一次 `delete`；三次关键值互不相同，且每次只有这一个参数和 `positionDeltas`；这些事件可以和其他对象的记录交错，但 copy、seed、deform 不能引用该网格；`keyformSets`、`keyformCopies`、`keyformDeletes` 也不能引用它，因为它们比日志更早回放；删除之后正好有一个 Warp，其顶层 `mesh_ids` 包含该网格，并且该 Warp 的关键值覆盖这三次的值。不满足就拒绝，不会猜一个接近的序列。

## 不能混为一谈

- 保留图层 ID 不等于顶点拓扑不变。轮廓变化可能让自适应网格重建。
- 绑定字段没变，不等于动作看起来没变。Warp 范围、骨骼采样和遮挡要实际看。
- 不把某次工程的层名、参数范围或顶点数写成通用常量。
- 分开汇报用户确认的画面，和自己完成的保存、重开、动作检查。

## 已经验证的边界

2026-10-02 的身体替换：前片与后摆的 alpha 有变化，腿部没有，所以只换了前两层。第一次加载报 `ArtMeshTopwear position deltas size mismatch: expected 626, got 576`。旧日志里该网格的三次关键值实际是 0、-8、8，随后删除 `ParamSkelChest`；动作由后面的 Warp 承担，且 `mesh_ids` 在 warp 操作顶层。当时画面已确认，原生保存、重开和完整动作复查还没做完。
