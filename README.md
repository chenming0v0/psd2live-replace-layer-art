# PSD2Live 局部原画替换

替换 PSD2Live 里已经绑定过的指定图层原画，保留图层身份，以及仍然有效的变形和动作。

这不是整份 PSD 重新导入，也不负责通用绘画。

## 这次是怎么做出来的

2026-10-02 晚上，我先和 Claude 5.5 处理角色身体原画的替换。对话一直聊到上下文满了，身体图层仍然没有换上，已有的拆层、绑定和动作也不能靠重新导入保住。

之后我买了中转站上的 GPT-6 Astra，让它连续跑了大约 5 小时。它先确认插件没有“只换已绑定图层像素”的入口，再对照工程里的当前贴图，而不是看两份 PSD 的文件名或哈希。前片和后摆有实质修复，腿部透明轮廓没有变化，所以没有一起替换。

第一次加载新副本时，软件报 `ArtMeshTopwear position deltas size mismatch: expected 626, got 576`。原因不是图片损坏，而是新的透明轮廓让网格重建，旧的胸部网格关键形却还在回放。那组关键形后来已经被删除，实际动作改由 Warp 承担。去掉这组失效回放后，副本才在软件里打开。

这个 skill 是那 5 小时的经验总结：哪些入口不能用、哪些像素该换、网格日志要满足什么条件才能清理，以及三份可以直接运行的脚本。

## 安装

用 Codex 的 skill 安装脚本：

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" --repo chenming0v0/psd2live-replace-layer-art --path . --name psd2live-replace-layer-art
```

也可以把本仓库放到 `%USERPROFILE%\.codex\skills\psd2live-replace-layer-art`，并保留仓库根目录的 `SKILL.md`。

## 使用

脚本在 `scripts/`，依赖 Python 3、Pillow、numpy 和 psd-tools。先另存当前工程，再按这个顺序运行：

```powershell
python scripts/compare_layers.py --project "baseline.psd2live" --psd "refined.psd" --layer "layer-id=psd-layer" --output "comparison.png"
python scripts/inspect_journal.py --project "baseline.psd2live" --check "MeshId:ParameterId"
python scripts/replace_layers.py --project "baseline.psd2live" --psd "refined.psd" --layer "layer-id=psd-layer" --output "candidate.psd2live"
```

只有检查脚本输出 `accepted: true` 时，才把同一个 `MeshId:ParameterId` 加到替换命令的 `--clean-obsolete-mesh`。替换脚本只写新文件，不覆盖输入。

判断规则、存档格式和不能做的事情写在 [SKILL.md](SKILL.md) 与 [references/archive-and-replay.md](references/archive-and-replay.md)。

## 边界

脚本通过，只说明新副本的结构和校验通过。还要用 PSD2Live 打开，检查合成画面和受影响的动作，再由软件自己保存并重新打开。

新像素超出原来的图层范围，或者旧网格动作仍然有效时，脚本会拒绝。这种情况不能靠补零、截断或删除有效动作来换取打开成功。

## 许可

[MIT](LICENSE)
