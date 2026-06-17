# Toast 布局调整 + 保存提示 设计

日期：2026-06-17

## 背景

1. 用户希望在设置中点"保存并关闭"后，得到一次明确反馈弹窗。
2. 当前 Toast 布局：顶部独占一行放关闭按钮 ×，下方一行放文字，视觉不协调。
3. 进一步希望 Toast 框可拖动边缘改变长宽，本次调整后在软件未退出前保持。

## 需求

### 需求 1：保存成功提示

在 `SettingsDialog._save_settings` 中，配置写入成功后、`accept()` 之前，弹出
`QMessageBox.information`：

> 设置修改成功！
> 部分设置将在下次打开软件时生效。

用户点确定后对话框关闭（accept）。

放弃此前"主题实时预览"的设想——不做任何主题预览逻辑。

### 需求 2：Toast 布局重构

移除"顶部关闭按钮行"。改为：

- 文本 `QLabel` 占满内容区，`AlignCenter`，通过 contentsMargins 左右留白
  （左侧 16px，右侧 36px 留出关闭按钮空间），使文字视觉居中且不与按钮重叠。
- 关闭按钮 × 用**绝对定位**：在 `resizeEvent` 中 `move()` 到右上角
  (x = width - btn - 6, y = 4)，浮于文字区右上角。
- 调整 `TOAST_MIN_HEIGHT` 等常量使整体更紧凑（约 56px）。

### 需求 3：Toast 边缘拖拽改大小

- `setMouseTracking(True)` 永久开启，`mouseMoveEvent` 中检测鼠标是否位于
  8px 边缘热区内，若是则切换为对应方向的 resize 光标（SizeHorCursor 等）。
- `mousePressEvent`：若在边缘热区，进入 resize 模式，记录 `_resize_edge`
  与起始 `geometry()` / 鼠标位置；否则保持原有"拖动移动窗口"逻辑。
- `mouseMoveEvent`（resize 模式）：根据边缘方向调整窗口 `geometry`
  （支持左/右/上/下/四角共 8 方向），受 `minimumSize` 约束。
- `mouseReleaseEvent`：保存 `_user_size = self.size()`（session 级记忆）。
- `show_toast`：若有 `_user_size` 则 `resize(_user_size)`，否则按内容计算；
  不再使用 `setFixedSize`，改为 `setMinimumSize + resize`，允许后续 resize。
- 位置记忆 `_user_position` 已存在，保持不变；大小记忆 `_user_size` 与之
  同为 session 级（实例属性，软件退出即清）。
- 边缘 resize 对所有显示中的 toast 启用；实际只有悬浮（pin）模式停留
  足够久可供拖拽，但大小记忆对所有 toast 生效。

## 涉及文件

- `src/ui/settings_dialog.py` — 保存提示弹窗
- `src/ui/toast_window.py` — 布局重构 + 边缘 resize + 大小记忆
- `src/app.py` — 无需改动

## 测试 / 验证

- 手动：打开设置 → 改任意项 → 保存并关闭 → 出现提示框。
- 手动：触发结果 Toast（pin 模式）→ 鼠标移到边缘出现 resize 光标 → 拖拽
  改变长宽 → 释放 → 再次触发 toast 仍为记住的大小。
- 手动：拖动 toast 移动位置（内部按下拖动）仍正常。
- 关闭按钮 × 仍在右上角，点击关闭悬浮 toast。
