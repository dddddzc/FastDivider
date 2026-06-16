"""FastDivider 入口程序

极速除法助手 - 选中数字，按快捷键即可计算。
轻量级 Windows 桌面工具，单文件 EXE，开箱即用。

启动流程：
1. 单实例检查（Named Mutex 防止重复启动）
2. sys.path 修复（确保 import 路径正确）
3. 全局异常钩子（捕获未处理异常写日志）
4. 日志系统初始化
5. Qt 应用创建
6. 主应用启动
"""

import sys
import logging
import traceback
import atexit
import ctypes
import ctypes.wintypes
from pathlib import Path

from src.version import (
    APP_NAME, APP_MUTEX_NAME, APP_DIR_NAME, APP_LOG_NAME,
    APP_CRASH_LOG_NAME, get_version,
)

# 日志目录（在任何 import 之前确定）
LOG_DIR = Path.home() / "AppData" / "Roaming" / APP_DIR_NAME
LOG_DIR.mkdir(parents=True, exist_ok=True)
CRASH_LOG = LOG_DIR / APP_CRASH_LOG_NAME

# ── 单实例守护（Named Mutex） ──
# 使用 Windows Named Mutex 防止同时运行多个 FastDivider 实例。
# Mutex 由 OS 管理生命周期：进程正常退出或崩溃时自动释放，无残留问题。

ERROR_ALREADY_EXISTS = 0x000000B7
MUTEX_NAME = APP_MUTEX_NAME

kernel32 = ctypes.windll.kernel32
kernel32.CreateMutexW.argtypes = [
    ctypes.c_void_p,      # lpSecurityAttributes (NULL = None)
    ctypes.c_int,         # bInitialOwner
    ctypes.c_wchar_p,     # lpName
]
kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE


class SingleInstanceGuard:
    """单实例守护：使用 Windows Named Mutex 防止重复启动

    在 QApplication 创建之前调用 ensure()：
    - 若 Mutex 已存在（另一个实例正在运行），弹窗提示后退出
    - 若 Mutex 创建成功，注册 atexit 释放，继续启动
    """

    _handle: ctypes.wintypes.HANDLE = None

    @classmethod
    def ensure(cls) -> None:
        """检查并获取单实例锁，若已有实例则弹窗退出"""
        cls._handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        err = ctypes.GetLastError()

        if err == ERROR_ALREADY_EXISTS:
            # 另一个实例正在运行
            kernel32.CloseHandle(cls._handle)
            cls._handle = None
            ctypes.windll.user32.MessageBoxW(
                0,
                f"{APP_NAME} 已在运行中，不能重复启动。",
                APP_NAME,
                0x40,  # MB_ICONINFORMATION
            )
            sys.exit(0)

        # 成功获取 Mutex，注册退出时释放
        atexit.register(cls._release)

    @classmethod
    def _release(cls) -> None:
        """释放 Mutex（atexit 或正常退出时调用）"""
        if cls._handle is not None:
            kernel32.CloseHandle(cls._handle)
            cls._handle = None


def write_crash_log(exc_type, exc_value, exc_tb) -> None:
    """全局异常钩子：捕获未处理异常并写入崩溃日志"""
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    timestamp = ""
    try:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        timestamp = "(unknown time)"

    crash_msg = f"\n{'='*60}\n[{timestamp}] FATAL CRASH\n{'='*60}\n{tb_text}\n"

    # 写入崩溃日志
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(crash_msg)
    except Exception:
        pass

    # 如果有控制台窗口，也输出到 stderr
    try:
        sys.stderr.write(crash_msg)
        sys.stderr.flush()
    except Exception:
        pass

    # 尝试弹出一个简单的错误提示（不依赖 Qt）
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{APP_NAME} 崩溃了！\n\n错误信息：{str(exc_value)}\n\n崩溃日志已保存至：\n{CRASH_LOG}",
            f"{APP_NAME} - 崩溃",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        pass


# 注册全局异常钩子（在任何其他代码之前）
sys.excepthook = write_crash_log


def setup_logging() -> None:
    """配置日志系统"""
    log_file = LOG_DIR / APP_LOG_NAME

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def main() -> None:
    """主入口"""
    # 单实例检查：防止重复启动
    SingleInstanceGuard.ensure()

    # 确保项目根目录在 sys.path 中
    if hasattr(sys, '_MEIPASS'):
        if sys._MEIPASS not in sys.path:
            sys.path.insert(0, sys._MEIPASS)
    else:
        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

    setup_logging()
    logger = logging.getLogger(APP_NAME)
    logger.info("=== %s 启动 ===", APP_NAME)
    logger.info("Python: %s", sys.version)
    logger.info("sys.executable: %s", sys.executable)
    logger.info("_MEIPASS: %s", getattr(sys, '_MEIPASS', '(开发环境)'))

    # 创建 Qt 应用（可能因 Qt 平台插件缺失而崩溃）
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication(sys.argv)
    except Exception as e:
        logger.critical("QApplication 创建失败: %s", e)
        # 这是 Qt 平台插件问题，直接报错退出
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Qt 初始化失败：{e}\n\n可能原因：缺少 Qt 平台插件。\n请检查 PyQt6 是否正确安装。",
            f"{APP_NAME} - 启动失败",
            0x10,
        )
        sys.exit(1)

    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(get_version())

    # 创建隐藏锚点窗口：确保 GUI 子系统进程拥有真实顶层窗口句柄
    # --windowed 打包时没有控制台窗口，也没有可见的顶层窗口（Toast 是 Tool 窗口），
    # 在部分 Windows 配置下，缺少顶层窗口锚点会导致 GetAsyncKeyState 轮询失效。
    # 关键：Tool 窗口不算"真正的顶层窗口"，不会被列入桌面窗口列表，
    # 必须使用普通窗口类型（Window）才能让 GetAsyncKeyState 正常工作。
    # 通过 FramelessWindowHint + 1x1 像素 + 屏幕外位置确保用户完全不可见。
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import Qt
    anchor = QWidget()
    anchor.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    anchor.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowDoesNotAcceptFocus
        | Qt.WindowType.WindowStaysOnBottomHint
    )
    anchor.setGeometry(-32000, -32000, 1, 1)  # 屏幕外 1x1 像素，完全不可见
    anchor.show()   # 必须先 show() 才能创建 HWND
    # 注意：不再调用 hide()。hide() 后窗口脱离桌面窗口列表，
    # 部分 Windows 版本下 GetAsyncKeyState 仍可能失效。
    # 1x1 + Frameless + 屏幕外位置足以保证用户完全看不到。

    # 通过 ctypes 直接修改窗口扩展样式：
    # 添加 WS_EX_NOACTIVATE (0x08000000) 防止窗口出现在 Alt+Tab 列表中，
    # 同时保持窗口在桌面窗口列表中的存在（这对 GetAsyncKeyState 正常工作是必需的）。
    # 注意：不能用 Qt.WindowType.Tool (WS_EX_TOOLWINDOW)，因为它会从桌面窗口列表中
    # 排除窗口，导致 GetAsyncKeyState 轮询对 --windowed 进程失效。
    GWL_EXSTYLE = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_APPWINDOW = 0x00040000
    user32_lib = ctypes.windll.user32
    hwnd = int(anchor.winId())
    ex_style = user32_lib.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    # 移除 WS_EX_APPWINDOW（会强制任务栏显示），添加 WS_EX_NOACTIVATE
    ex_style = (ex_style & ~WS_EX_APPWINDOW) | WS_EX_NOACTIVATE
    user32_lib.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex_style)

    logger.info("锚点窗口 HWND: 0x%X, isVisible: %s, exStyle=0x%X",
                hwnd, anchor.isVisible(), ex_style)

    logger.info("QApplication 创建成功")

    # 创建并启动主应用
    try:
        from src.app import FastDividerApp
        main_app = FastDividerApp(app)
        main_app.start()
    except Exception as e:
        logger.critical("主应用启动失败: %s", e, exc_info=True)
        ctypes.windll.user32.MessageBoxW(
            0,
            f"应用启动失败：{e}\n\n崩溃日志：{CRASH_LOG}",
            f"{APP_NAME} - 启动失败",
            0x10,
        )
        sys.exit(1)

    logger.info("主应用启动成功，进入事件循环")

    # 进入事件循环
    try:
        exit_code = app.exec()
    except Exception as e:
        logger.critical("事件循环异常: %s", e, exc_info=True)
        exit_code = 1

    logger.info("%s 正常退出，代码: %d", APP_NAME, exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
