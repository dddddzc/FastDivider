# AGENTS.md — FastDivider 工作手册

> 本文件是 AI 协作时的权威项目指引，优先级高于个人偏好。
> 用户显式指令优先于本文件；与本文件冲突时按用户指令执行，但请简短说明偏差。
> 用户面向文档见 `README.md`；此处只写"代理必须知道的事"。

## 项目定位

FastDivider（极速除法助手）是 **Windows-only** 单文件桌面工具：选中数字 → 按全局快捷键 → Toast 显示结果。系统托盘常驻、单实例运行、支持 GitHub Releases 自动更新。Python 3.14 x64 + PyQt6 + 大量 ctypes 调用，不使用 `requests`/`keyboard`/`pynput`/`comtypes`。

## 速查表

| 项 | 值 |
|---|---|
| 版本唯一源 | `pyproject.toml` 的 `version` 字段（当前 1.1.2） |
| 身份/路径常量集中地 | `src/version.py`（`APP_NAME`、`APP_MUTEX_NAME`、GitHub repo、注册表键等） |
| 入口 | `src/main.py:main()` |
| 主应用协调者 | `src/app.py:FastDividerApp(QObject)` |
| 配置/历史目录 | `%APPDATA%\FastDivider\`（`config.json`、`history.json`、`fastdivider.log`、`crash.log`） |
| 正式构建 | `python build.py` → `dist/FastDivider.exe` + `dist/FastDivider-v{ver}.zip` |
| 调试构建 | `python build_debug.py` → `dist/FastDivider_debug.exe`（保留控制台） |
| 发布流程助手 | `python release.py`（无副作用，仅打印步骤） |
| 开发运行 | `pip install PyQt6 pyperclip pywin32` 后 `python -m src.main` |

## 代码规范

- **导入风格**：绝对导入，根为 `src.`（如 `from src.core.config import ConfigManager`）。禁止相对导入。`src/__init__.py`、`src/core/__init__.py`、`src/ui/__init__.py` 均存在，`src` 是包。
- **惰性局部导入**：为避免循环导入与推迟 Qt widget 创建，`app.py`、`updater.py` 在函数内 `import`。**PEP 762 陷阱（Python 3.14）**：函数内 `import X` 会让 `X` 在整函数内被视作局部变量，若 `X` 已在模块级导入且局部导入语句之前使用 → `UnboundLocalError`。新增局部导入时，确认该名未在模块顶部导入；若已顶部导入，**不要**再在函数内重复导入。
- **类型注解**：全量使用现代小写泛型（`set[int]`、`dict[str, Any]`、`list[HistoryEntry]`、`Optional[...]`、`Callable[...]`）。所有公共方法均标注返回类型。
- **信号/槽**：仅使用 new-style（`pyqtSignal` 类属性 + `.connect(slot)` + `.emit(args)`）。跨线程一律 `Qt.ConnectionType.QueuedConnection`。回调槽建议加 `@pyqtSlot`。托盘菜单用 `action.triggered.connect(self.xxx_requested.emit)` 直接转发。
- **Qt 枚举**：完整限定形式 `Qt.WindowType.FramelessWindowHint`、`Qt.AlignmentFlag.AlignCenter`，禁用裸 `Qt.FramelessWindowHint`。
- **命名**：PascalCase 类、snake_case 方法/函数、前导下划线表私有、UPPER_SNAKE 模块常量。
- **文档字符串**：三双引号；模块/类说明职责；方法用 Google 风格 `Args:`/`Returns:`/`Raises:`。中文用于人向注释与面向用户文案，英文用于设计文档。
- **日志**：每模块 `logger = logging.getLogger(__name__)`，惰性 `%`-格式（`logger.info("配置: %s", path)`）。`logging.basicConfig` 仅在 `main.py` 调一次（文件 handler，INFO 级）。`print` 仅在构建脚本 `build*.py`/`release.py` 中使用。
- **错误处理**：try/except 配 `logger.error/warning` 后优雅降级（热键注册失败不崩、剪贴板 `finally` 恢复、配置 JSONDecodeError 回退默认）。非关键原生调用允许 `try/except Exception: pass`，但范围要窄。

## 架构规则（不可破坏）

### 线程模型

- **Qt 主线程**承担所有 UI + 两个 `QTimer` 轮询：`HotkeyManager` 50ms 热键轮询、`HotkeyRecordButton` 100ms 录制轮询。
- **后台线程**仅两类：`threading.Thread(daemon=True)`（`ClipboardReader` 的 UIA/剪贴板读取）与 `QThread`（`Updater` 的检查/下载）。
- **跨线程交接必须经 Qt 信号 + `QueuedConnection`**，严禁在工作线程直接动 UI。`app.py` 用 `_capture_signal`/`_text_received_signal` 完成主线程交接。
- **重入保护**：`app.py` 用 `threading.Lock` 非阻塞 acquire，避免在已捕获时再次触发。
- **主线程禁止 `time.sleep` 阻塞**：剪贴板 `time.sleep(0.05/0.25/0.08)` 必须在后台线程内执行。

### Windows 特定模式

- **单实例锁**：`src/main.py` 用 `kernel32.CreateMutexW` Named Mutex（`Global\FastDivider_SingleInstance_Mutex`），在 `QApplication` 之前检查；`ERROR_ALREADY_EXISTS (0xB7)` 弹 `MessageBoxW` + `sys.exit(0)`。OS 自动释放，崩溃无残留。**不要**改用 `QSharedMemory`（崩溃留残）或 PID 锁（重用风险）。
- **隐藏锚点窗口（load-bearing）**：`--windowed` 打包后 GUI 子系统进程若无顶层窗口锚点，`GetAsyncKeyState` 失效。`main.py:189-217` 创建 1×1 像素、屏幕外 `(-32000, -32000)`、**普通 Window 类型**（**不可用 `Qt.Tool`**，`WS_EX_TOOLWINDOW` 会脱离桌面窗口列表）、`show()` 创建 HWND 后**不 hide**、`SetWindowLongPtrW` 加 `WS_EX_NOACTIVATE (0x08000000)` 移除 `WS_EX_APPWINDOW (0x00040000)` 防 Alt+Tab 出现。
- **ctypes `SendInput` INPUT 结构体**：`clipboard_reader.py:38-94` 必须保留 `_INPUT_UNION`（`MOUSEINPUT`+`KEYBDINPUT`+`HARDWAREINPUT`）+ `_anonymous_=["_"]`，`dwExtraInfo` 用 `POINTER(c_ulong)` 对应 `ULONG_PTR`。x64 上错误 padding/缺失 union 会崩溃。`cbSize=sizeof(INPUT)`，结果校验 `result != 4`。
- **热键轮询**：`HotkeyManager._poll_keys` 用释放触发（active→released 转换才回调），确保 Ctrl+C SendInput 时修饰键已释放。回调在主线程同步执行，**只允许 `emit()` Qt 信号**，不做阻塞工作。
- **精确匹配**：`_check_hotkey_match` 用家族集语义（`_MOD_FAMILY`：shift/ctrl/alt 各家族含通用 0x10/0x11/0x12 + 左右 0xA0-0xA5），不允许多余修饰家族；纯修饰键热键（如 `ctrl+shift`）禁止任何已知非修饰键同时按下。
- **COM/UIA**：`uia_reader.py` 不用 `comtypes`，直接 vtable 调用。所有 COM 指针在嵌套 `finally` 中 `Release`，泄漏即崩溃。`pythoncom.CoInitialize` 在函数内局部调用。

### 数据存储与时区

- **历史时间戳**存 UTC ISO 8601：`datetime.now(timezone.utc).isoformat()`（`app.py`）。UI 显示时 `history_dialog.py:_format_timestamp` 用 `.astimezone()` 转本地，`strftime("%Y-%m-%d %H:%M:%S")`。**禁止原样展示 UTC 字符串。**
- **配置迁移**：`ConfigManager._migrate_config` 自动剔除 `DEFAULT_CONFIG` 之外的键（如旧 `reset_hotkey`）并钳制 `decimal_places` 到 `[0,9]`。增删配置键无需手写迁移逻辑。
- **`ConfigManager.get(key, default)`**：传 `None` 作 default 会回落到 `DEFAULT_CONFIG[key]`；显式传其他值才会返回该值。

### 对话框复用模式

- `SettingsDialog`、`HistoryDialog`、`UpdateDialog` 在 `FastDividerApp` 中**懒创建并复用**，不每次 `new`。
- 重开设置时调用 `self._settings_dialog._load_values()` 刷新控件值（而非重建实例）。新增控件时确保 `_load_values` 同步更新。
- 恢复默认调用 `config.reset_to_defaults()` + `_load_values()` + `hotkey_manager.update_hotkey(...)`，最后 `accept()`。

## 关键陷阱清单（带行号锚点）

| 陷阱 | 位置 | 说明 |
|---|---|---|
| 隐藏锚点窗口 | `src/main.py:189-217` | `--windowed` 构建必备，详见架构规则 |
| `INPUT` union 结构体 | `src/core/clipboard_reader.py:38-94` | x64 padding/union 错误即崩，勿"简化" |
| 单实例 Mutex | `src/main.py:40-85` | OS 释放，勿换实现 |
| 释放触发热键 | `src/core/hotkey_manager.py:301-322` | 按下触发会与 Ctrl+C 冲突 |
| F13-F24 已从 `VK_NAMES` 移除 | `src/core/hotkey_manager.py:45-52` | `GetAsyncKeyState` 对 0x85 等返回虚假按下，会阻断纯修饰键热键匹配 |
| SettingsDialog 复用 | `src/app.py:277-288` | 重开调 `_load_values()`，不重建 |
| UTC→本地时间 | `src/app.py:253` 存、`src/ui/history_dialog.py:26-39` 显 | 中间任何环节都勿展示原始 UTC |
| `sys.excepthook` 早注册 | `src/main.py:127` | 在 `main()` 之前，崩溃路径不依赖 Qt |

## 已知技术债与意外发现

代理修改下列区域前请三思：

- **`VK_NAMES` 中 F8 (0x77) 缺失**（`hotkey_manager.py:50-52`）：f7 (0x76) 与 f9 (0x78) 之间没有 f8。注释只说"移除 F13-F24"，未提及 F8。修改前应确认是否为意外遗漏。
- **`SettingsDialog` 版本标签硬编码 "v1.0"**（`settings_dialog.py:188`）：未从 `version.get_version()` 取值，长期与实际版本不同步。
- **`pyproject.toml` 声明 `requires-python = ">=3.10"`**，但实际开发/构建环境为 Python 3.14 x64（spec/`__pycache__`/README 均印证）。PEP 762 是活跃陷阱。
- **`Updater` 主线程同步 `_http_get`**：`updater.py:344-366` 在启动 `UpdateDownloadThread` 之前同步取下载 URL，会短暂阻塞主线程。
- **`UpdateDownloadThread` 一次性读全 ZIP 入内存**：`raw = _http_get(url, timeout=300)` 后 `f.write(raw)`，非流式；当前 EXE 体积可接受。
- **`ClipboardReader` 固定 sleep**：0.05/0.25/0.08 秒是经验调优值；改值可能让慢应用复制不可靠。
- **`SettingsDialog` 始终浅色主题**：`_LIGHT_STYLE` QSS 固定（`settings_dialog.py:362-388`），与 Toast 主题解耦，勿误改。

## 自动生成文件（勿手改）

| 文件 | 生成者 | 处理方式 |
|---|---|---|
| `FastDivider.spec` | PyInstaller（绝对路径） | `build.py`/`build_debug.py` 每次重建，勿手改 |
| `version_info.txt` | `build.py:sync_version_info()` 从 `pyproject.toml` 生成 | 改版本号改 `pyproject.toml`，勿改本文件 |
| `dist/FastDivider-v*.zip` | `build.py` 打包后自动归档 | 发布到 GitHub Release 的资产 |
| `build/`、`__pycache__/`、`*.log` | 构建/运行产物 | `.gitignore` 已忽略 |

`build.py` 与 `build_debug.py` 的**关键运行时差异**是 `--windowed` 参数：正式版有（无控制台，依赖隐藏锚点窗口让 `GetAsyncKeyState` 工作），调试版无（保留控制台看实时日志）。其余差异：`--name`（`FastDivider` vs `FastDivider_debug`）、`sync_version_info()` + `--version-file`（仅正式版）、打包后自动生成 ZIP（仅正式版）、`clean_build` 清理的 spec/exe 名不同。改任一脚本的 PyInstaller 参数请同步另一脚本。

## 构建与发布流程

### 1. 升版本号

编辑 `pyproject.toml` 的 `version` 字段（如 `1.1.2`）。这是版本唯一源，`build.py` 会自动同步到 `version_info.txt` 和 EXE 版本资源。升版前先查已有标签避免冲突：`git tag --list "v*"`。

### 2. 构建

```bash
python build.py
```

自动执行：清理上次产物 → 同步 `version_info.txt` → 查找 pywin32 DLL 与 Qt 平台插件 → PyInstaller `--onefile --windowed` → 生成 `dist/FastDivider.exe`（约 37 MB）和 `dist/FastDivider-v{ver}.zip`（约 37 MB）。

### 3. 验证

运行 `dist/FastDivider.exe`，确认热键、Toast、托盘、历史记录、设置均正常。详见下方"测试与验证策略"。

### 4. 提交代码

```bash
git add pyproject.toml version_info.txt src/ AGENTS.md   # 按实际改动选择
git commit -m "feat: <简要描述> (v{ver})"
```

**不要提交**：`build/`、`dist/`、`FastDivider.spec`（自动生成）、`*.log`、临时 `config.json`。`version_info.txt` 虽自动生成但已纳入版本控制，需提交以保持同步。

### 5. 推送代码和标签

```bash
git tag v{ver}
git push https://dddddzc:$(gh auth token)@github.com/dddddzc/FastDivider.git master v{ver}
```

**注意**：代理环境中 `gh auth setup-git` 配置的 credential helper 非交互推送会失败（报 `could not read Username`）。必须用 `$(gh auth token)` 内联 token 推送。`gh auth status` 确认已登录。

### 6. 创建 GitHub Release 并上传产物

`gh release create` 依赖 GraphQL 端点，在代理环境中可能报 `EOF` 失败。改用 REST API 两步完成：

```bash
# 6a. 创建 Release（--jq .id 提取 release ID）
gh api repos/dddddzc/FastDivider/releases -X POST \
  -f tag_name="v{ver}" -f name="v{ver}" -f body="<release notes>" --jq .id

# 6b. 上传 ZIP 产物（用上一步返回的 release ID）
TOKEN=$(gh auth token)
curl.exe -s -L -X POST \
  -H "Authorization: token $TOKEN" \
  -H "Content-Type: application/zip" \
  --data-binary @"dist/FastDivider-v{ver}.zip" \
  "https://uploads.github.com/repos/dddddzc/FastDivider/releases/<release_id>/assets?name=FastDivider-v{ver}.zip"
```

### 约束

- Release tag 格式必须 `vX.Y.Z`。
- 附件必须含以 `FastDivider` 开头、`.zip` 结尾的 ZIP，否则自动更新无法识别。
- `gh release create`（GraphQL）不可靠时，用 `gh api`（REST）+ `curl.exe` 上传替代。
- `release.py` 会按上述步骤打印指引，不执行任何副作用。

## 测试与验证策略

本项目当前**无自动化测试套件**。验证依赖手动流程，请每次改动后至少：

1. 开发态：`python -m src.main` 跑起来，触发热键两次验证计算、Toast 显示与定位、托盘菜单、历史记录、设置保存与恢复默认。
2. 打包态：`python build_debug.py` 后运行 `dist/FastDivider_debug.exe`，看控制台日志无 ERROR，热键仍可捕获（验证隐藏锚点窗口未失效）。
3. 改动 UI 主题/动画时：试切换 light/dark、pin/unpin、拖动边缘缩放、多显示器插拔。
4. 改动更新流程时：用错误版本号触发"无更新"路径，再手动构造一个"新版本" GitHub Release 跑通确认。
5. 改动配置项时：删 `config.json` 后启动验证默认值；带旧 `reset_hotkey` 的配置启动验证迁移逻辑；`decimal_places` 设为 -1 或 100 验证钳制。

## 代理工作流建议

- **改代码前**：先 `Grep` 找所有引用点，确认改动面。改 `src/version.py` 常量前尤其要全局搜。
- **改 UI 时**：留意 `app.py` 中的对话框复用模式，新增控件 → 在 `_load_values` 与 `_save_settings` 双向同步。
- **改 ctypes 结构时**：保持 union 与 `_anonymous_` 模式，x64 上的 padding 极敏感。
- **改热键逻辑时**：纯修饰键热键（`ctrl+shift`、`ctrl+alt`）路径必须扫描 `_NON_MODIFIER_KNOWN_VKS` 排除误触发；勿把 F13-F24 加回 `VK_NAMES`。
- **改剪贴板流程时**：保留 `finally` 中的剪贴板恢复；`time.sleep` 时序勿随意调。
- **改 COM/UIA 时**：每个 `IUnknown*` 都要有 `Release` 出口，否则长生命周期下会崩。
- **改完后**：按"测试与验证策略"跑一遍手动验证；提交前用 `git diff` 自检，确认未误删 `atexit`、`excepthook`、锚点 `show()` 等关键行。
- **不要提交**：`build/`、`dist/`、`*.spec`（已被忽略或自动生成）、`crash.log`、`fastdivider.log`、临时 `config.json`。

## 文件地图

```
FastDivider/
├── README.md                    # 用户文档
├── AGENTS.md                    # 本文件（代理手册）
├── pyproject.toml               # 版本/依赖/入口点（版本唯一源）
├── requirements.txt             # 运行+构建依赖
├── build.py                     # 正式打包（--onefile --windowed + zip + version_info）
├── build_debug.py               # 调试打包（保留控制台，无 zip/version_info）
├── release.py                   # 发布步骤打印助手
├── FastDivider.spec             # 自动生成，勿手改
├── version_info.txt             # 自动生成，勿手改
├── docs/superpowers/specs/      # 设计文档
└── src/
    ├── __init__.py
    ├── version.py               # 身份/版本/路径常量集中地
    ├── main.py                  # 入口：日志、单实例锁、QApplication、锚点窗口、excepthook
    ├── app.py                   # FastDividerApp：状态机、模块协调、对话框复用
    ├── core/
    │   ├── config.py            # ConfigManager（JSON 持久化 + 迁移）
    │   ├── clipboard_reader.py  # ClipboardReader（UIA → Ctrl+C 后备，SendInput）
    │   ├── uia_reader.py        # 原生 COM UI Automation 文本读取
    │   ├── hotkey_manager.py    # GetAsyncKeyState 轮询 + 录制
    │   ├── number_parser.py     # 严格唯一数字解析（整数/小数/科学/千分位）
    │   ├── history.py           # HistoryManager + HistoryEntry dataclass
    │   └── updater.py           # Updater + UpdateCheckThread + UpdateDownloadThread
    ├── ui/
    │   ├── toast_window.py      # ToastWindow（手动 paintEvent 阴影、拖动、边缘缩放）
    │   ├── tray_icon.py         # TrayIcon（右键菜单，new-style 信号转发）
    │   ├── settings_dialog.py   # SettingsDialog + HotkeyRecordButton（Snipaste 风格）
    │   ├── history_dialog.py    # HistoryDialog（UTC→本地时间格式化）
    │   └── update_dialog.py     # UpdateDialog（模态三阶段：确认/下载/安装）
    └── resources/
        ├── icon.ico / icon.png / icon_design.png
```

## 启动时序（`src/main.py:main` 严格顺序，勿调换）

1. 创建日志目录 `%APPDATA%\FastDivider\`（在任何可能失败的 import 之前）。
2. 注册 `sys.excepthook = write_crash_log`（写 `crash.log` + stderr + 原生 `MessageBoxW`，不依赖 Qt）。
3. `SingleInstanceGuard.ensure()` 检查互斥量，已存在则弹窗 + `sys.exit(0)`。
4. `sys.path` 修正（`sys._MEIPASS` 或项目根）。
5. `setup_logging()`：仅文件 handler，INFO 级。
6. `QApplication` 创建在 try/except 中，平台插件失败 → 原生 `MessageBoxW` + exit 1。
7. `app.setQuitOnLastWindowClosed(False)`（无可见主窗口，托盘即代表存在）。
8. 创建隐藏锚点 `QWidget`（`show()` 后不 `hide()`，加 `WS_EX_NOACTIVATE`）。
9. `FastDividerApp(app).start()`，`app.exec()`。
