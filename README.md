# FastDivider 极速除法助手

选中数字，按快捷键，即刻完成除法计算。

轻量级 Windows 桌面工具，系统托盘运行，单文件 EXE，开箱即用。

## 使用方式

1. 在任意应用中选中第一个数字（被除数），按快捷键 → Toast 提示"已记录数字：X"
2. 选中第二个数字（除数），再按快捷键 → Toast 显示计算结果 A÷B
3. 托盘菜单"重置"可清除当前记录，重新开始

默认快捷键：`ctrl+shift`（可在设置中修改）

## 项目结构

```
FastDivider/
├── src/
│   ├── main.py                 # 入口（单实例锁、崩溃防护、Qt初始化、锚点窗口）
│   ├── app.py                  # 主应用（状态机、模块协调）
│   ├── core/
│   │   ├── config.py           # 配置管理（JSON持久化）
│   │   ├── hotkey_manager.py   # 全局快捷键（GetAsyncKeyState轮询）
│   │   ├── clipboard_reader.py # 剪贴板读取（SendInput模拟Ctrl+C）
│   │   ├── number_parser.py    # 数字解析（整数/负数/小数/科学计数法/千位分隔）
│   │   ├── history.py          # 历史记录（JSON持久化、导出TXT）
│   │   └── updater.py          # 自动更新（GitHub Releases API检查/下载/替换）
│   ├── ui/
│   │   ├── toast_window.py     # Toast弹窗（手动阴影绘制、悬浮模式）
│   │   ├── tray_icon.py        # 系统托盘（右键菜单）
│   │   ├── settings_dialog.py  # 设置界面（按键录制修改快捷键）
│   │   └── history_dialog.py   # 历史记录界面（复制/清空/导出）
│   └── resources/
│       ├── icon.ico
│       └── icon.png
├── build.py                    # 正式版打包（--onefile --windowed）
├── build_debug.py              # 调试版打包（--onefile，保留控制台）
├── pyproject.toml
└── requirements.txt
```

## 技术方案

**全局快捷键**：`GetAsyncKeyState` + `QTimer` 50ms 轮询。Python 3.14 x64 上 `WH_KEYBOARD_LL`、`RegisterHotKey`、`keyboard` 库、`pynput` 的钩子回调均不触发，轮询是目前唯一可靠的方案。采用释放触发（按键组合从按下→释放时才触发回调），确保修饰键已物理释放，避免与 Ctrl+C 模拟冲突。匹配逻辑使用家族集语义和精确匹配，不允许多余修饰键。

**剪贴板读取**：ctypes `SendInput` 模拟 Ctrl+C，`pyperclip` 读取剪贴板内容。INPUT 结构体在 x64 上需正确定义 union（`_anonymous_` 模式），`dwExtraInfo` 使用 `POINTER(c_ulong)` 对应 `ULONG_PTR`。耗时操作在后台线程执行，通过 `QueuedConnection` 信号回主线程。

**--windowed 打包兼容**：打包后无控制台窗口也无可见顶层窗口，`GetAsyncKeyState` 对 GUI 子系统进程可能失效。修复方案：创建 1x1 像素屏幕外隐藏锚点窗口（普通 Window 类型，不用 Tool），通过 ctypes `SetWindowLongPtrW` 添加 `WS_EX_NOACTIVATE` 防止 Alt+Tab 出现。

**单实例锁**：ctypes `CreateMutexW` Named Mutex（`Global\FastDivider_SingleInstance_Mutex`），OS 自动释放，无残留风险。

## 配置项

配置文件：`%APPDATA%\FastDivider\config.json`

| 配置键 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| hotkey | string | "ctrl+shift" | 主快捷键（记录/计算） |
| display_duration | float | 2 | 结果显示时长（秒） |
| toast_duration | float | 1 | 提示 Toast 时长（秒） |
| pin_mode | bool | false | 结果悬浮模式 |
| display_position | string | "bottom_right" | Toast 位置 |
| decimal_places | int | 2 | 小数位数（0-9） |
| auto_start | bool | false | 开机自启动 |
| theme | string | "light" | 主题（light/dark） |
| history_max | int | 100 | 最大历史记录条数 |

快捷键格式：`ctrl+shift`、`ctrl+alt+d`、`shift+f1` 等

## 构建与运行

开发环境：

```
pip install PyQt6 pyperclip pywin32
python -m src.main
```

正式版打包：

```
pip install PyInstaller
python build.py
# 输出 dist/FastDivider.exe
```

调试版打包：

```
python build_debug.py
# 输出 dist/FastDivider_debug.exe（保留控制台窗口）
```

## 自动更新

FastDivider 支持通过 GitHub Releases 自动检查和下载更新：

- **启动时自动检查**：每次启动时后台静默检查 GitHub 是否有新版本，有新版本时弹窗提示
- **手动检查**：托盘菜单 →「🔍 检查更新」随时手动检查
- **一键更新**：确认更新后自动下载新版本 EXE，通过替换脚本完成替换并自动重启

**发布新版本的流程**：

1. 修改 `pyproject.toml` 中的 `version` 字段（如 `1.0.1`）
2. 运行 `python build.py` 构建新版本（自动生成 EXE 和 ZIP）
3. 在 GitHub 创建 tag 并发布 Release：
   ```
   git tag v1.0.1
   git push origin v1.0.1
   ```
4. 在 GitHub Releases 页面将 `dist/FastDivider-v1.0.1.zip` 上传为附件

**要求**：Release 的 tag 格式必须为 `vX.Y.Z`（如 `v1.0.1`），且附件中必须包含以 `FastDivider` 开头、`.zip` 结尾的 ZIP 包。

## 已知限制

- `SendInput` 模拟 Ctrl+C 依赖目标应用支持复制操作，终端和部分游戏可能无效
- Toast 半透明效果依赖 `WA_TranslucentBackground`，少数显卡驱动可能有渲染问题
- 开机自启动写入注册表 `HKCU\...\Run`，仅打包后 EXE 有效
- Python 3.14 PEP 762 改变了变量作用域规则：函数内 `import X` 会让 X 成为局部变量，与模块级同名导入冲突会导致 `UnboundLocalError`，应避免在函数内局部导入已在模块级导入的模块

## 日志

运行日志：`%APPDATA%\FastDivider\fastdivider.log`
崩溃日志：`%APPDATA%\FastDivider\crash.log`

调试版 EXE 在控制台窗口中实时输出所有日志。
