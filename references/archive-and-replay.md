# 存档与回放

这是本地 PSD2Live v1 存档的已观察结构，不是所有版本的保证。优先读当前程序源码或格式文档，不修改应用源代码来绕过工程校验。

## 查证位置

本地源码的相关模块通常位于 `src/main/kotlin/io/github/psd2live/`：

- `project/ProjectArchive.kt`：ZIP 清单和 SHA-256 校验。
- `project/ProjectSession.kt`：解包到独立临时目录，再安装 HEAD 快照。
- `agent/AgentWorkspaceStore.kt`：图层编码、像素 blob、历史读写。
- `agent/ViewModelAgentWorkspace.kt`：修订号、原生保存、工程安装。
- `core/RigEditOverlay.kt`：按序回放关键形，校验顶点数组长度。

## v1 结构

所有 JSON 使用结构化解析和序列化。`sha256(text)` 指 UTF-8 字节的 SHA-256 小写十六进制。

| 内容 | 位置或规则 |
| --- | --- |
| 文件清单 | `manifest.json`，含 `format: PSD2Live`、`version: 1`、`projectId`、`files` |
| 清单哈希 | `files` 映射每个非 manifest 文件路径到其原始字节 SHA-256 |
| 原始源文件 | `source/original.psd`；局部替换不覆盖它 |
| UI 状态 | `workspace.json`，含 `selectedHistoryNodeId` |
| 工程前缀 | `workspace/{projectId}/` |
| 当前历史 | `{prefix}HEAD.json`，含 `headNodeId` 与 `nodeOrder` |
| 节点 | `{prefix}history/nodes/{sha256(node.id)}.json` |
| 快照 | `{prefix}history/snapshots/{sha256(node.snapshotHash)}.json` |
| 图层像素引用 | `rgbaBlob = sha256(非预乘 RGBA 原始字节)` |
| PNG 资源 | `{prefix}blobs/{sha256(rgbaBlob)}-{rasterWidth}x{rasterHeight}.png` |

PNG 路径有两层哈希：先对 RGBA 字节求摘要，再对该十六进制字符串求摘要。不是 PNG 文件摘要。解码 PNG 后验证尺寸和 RGBA 哈希。

当前快照包括 `layers`、`settings`、`rigEdits`、可见性、已删除图层、父级和网格设置等。`layers` 可能保留已删除的历史源层；不能把存储层数直接当作活动图层数。

## 构造独立候选副本

1. 校验基线 ZIP 清单，按 HEAD 找到当前节点和快照；不要猜“最新文件”。
2. 深复制当前快照。将 PSD 目标图层的 RGBA 放到源画布坐标，确认可见像素全部处于旧 raster 框内，再按旧框裁切。
3. 写入内容寻址 PNG，更新相应 `rgbaBlob`。除明确评估的回放兼容修正外，其他字段保持不变。
4. 追加唯一节点，`parentId` 指向旧 HEAD，包含 `id`、`revisionId`、`snapshotHash`、`summary`、`actor`、UTC `createdAt`、`version`。节点文件和快照文件不得覆盖旧内容。
5. 追加 `nodeOrder`、更新 HEAD 和 UI 选中节点，重建 manifest 的原始字节校验和。写到不存在的新输出文件。
6. 检查 ZIP 可读、清单完整、旧资源不变、未涉及图层不变、绑定差异在预期范围内。

### 修订号陷阱

原生 `revisionId` 是对 Kotlin 内部规范化状态求哈希，不是对 JSON 求哈希。不要把外部 JSON 摘要声称为原生修订号。

已观察版本允许加载外部唯一快照标识，并在原生保存时重新生成正常修订；但打开可能显示未保存星号。采用这一回退方式前必须核查当前加载/保存逻辑，之后必须原生保存并重开验证。若当前版本验证原生修订且无法准确计算，停止该回退方案，不关闭校验。

## 顶点数不匹配的判断

错误例：`Mesh ArtMeshTopwear position deltas size mismatch: expected 626, got 576`。

透明轮廓参与自适应网格生成。原画的 raster 尺寸没变，顶点数仍可能变。旧 `positionDeltas` 按顶点索引存储，不能补零或截断。

加载时先应用 `keyformSets`、`keyformCopies`、`keyformDeletes`，再按顺序回放 `authoringJournal`。只看其中一个来源会漏掉真正触发错误的事件。网格的三次 `set` 不必在日志里连续；其他对象的 copy 可以夹在中间。

不要手写一套新的清理条件。运行 `scripts/inspect_journal.py --check 网格ID:参数`，它和 `replace_layers.py` 调用同一个 `plan_obsolete_mesh_removal`。当前接受的结构是：

```text
set mesh:M，参数 P 的一个关键值，geometry 只有 positionDeltas
（可以夹着不引用 M 的其他事件）
set mesh:M，参数 P 的第二个不同关键值
set mesh:M，参数 P 的第三个不同关键值
delete mesh:M，parameter P
warp，顶层 mesh_ids 包含 M
set warp:W，参数 P，关键值覆盖上面三次
```

关键值从日志读取并写进输出，不存在固定的 0、-8、8。`mesh_ids` 在已验证存档中位于 warp 操作顶层，不在 `warp` 对象内部。以下任一情况都拒绝，而不是放宽条件：

- 该网格不是正好四条事件，或 delete 不是同一参数。
- set 带有其他参数、通道或几何字段。
- copy、seed、deform 引用该网格，或三个早期关键形列表仍含该网格。
- 删除后不是正好一个 Warp 覆盖全部三个关键值。

清理只改新快照的 `authoringJournal`。旧历史节点和基线不动。若旧网格关键形仍有效，就没有可用的替换路径；停下来说明，不用删有效动作换取打开成功。

## 界面操作经验

Windows 文件对话框可能作为主窗口截图之外的第二张截图返回，`list_windows` 不一定单列它。使用实际返回的对话框截图 ID 和该截图内坐标操作；主窗口标题、Pane 焦点信息不证明文件名输入框已获焦。

选中条目后刷新确认文件名，再点“打开”。双击可能在加载后落到模型界面并选中图层，所以要刷新判断当前状态，不沿用旧坐标。加载成功应由标题、无错误提示、模型实际渲染和 MCP 状态共同确认。
