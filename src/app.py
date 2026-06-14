"""主应用模块

FastDivider 应用核心逻辑，管理状态流转和各模块协调。

状态机：
    WAIT_FIRST_NUMBER -> 等待第一次按键（记录被除数）
    WAIT_SECOND_NUMBER -> 等待第二次按键（记录除数并计算）

流程：
    1. 用户选中数字，按快捷键 -> 获取选中文本 -> 解析数字
    2. 第一次成功 -> 记录 A，显示 Toast "已记录数字：X"
    3. 第二次成功 -> 记录 B，计算 A÷B，显示结果 Toast
"""

import logging
import threading
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, Qt

from src.core.config import ConfigManager
from src.core.number_parser import parse_number, format_division, format_number_display
from src.core.clipboard_reader import ClipboardReader
from src.core.hotkey_manager import HotkeyManager
from src.core.history import HistoryManager
from src.ui.toast_window import ToastWindow
from src.ui.tray_icon import TrayIcon

logger = logging.getLogger(__name__)


class AppState(Enum):
    """应用状态枚举"""
    WAIT_FIRST_NUMBER = auto()   # 等待记录被除数
    WAIT_SECOND_NUMBER = auto()  # 等待记录除数


class FastDividerApp(QObject):
    """FastDivider 主应用

    协调配置管理、快捷键监听、剪贴板读取、
    Toast 显示、系统托盘和历史记录等模块。
    """

    # 信号：用于在快捷键回调中安全地触发 UI 操作
    _capture_signal = pyqtSignal()
    _text_received_signal = pyqtSignal(str)

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app

        # 核心模块
        self._config = ConfigManager()
        self._clipboard = ClipboardReader()
        self._history = HistoryManager(
            self._config.history_path,
            self._config.get("history_max", 100),
        )

        # 应用状态
        self._state = AppState.WAIT_FIRST_NUMBER
        self._first_number: Optional[float] = None

        # 防重入锁：防止快速连按快捷键导致并发剪贴板操作
        self._capture_lock = threading.Lock()

        # UI 模块
        self._toast = ToastWindow(
            display_position=self._config.get("display_position", "bottom_right"),
            theme=self._config.get("theme", "light"),
            pin_mode=self._config.get("pin_mode", False),
        )

        # 快捷键管理（仅一个快捷键，用于记录/计算）
        self._hotkey_manager = HotkeyManager(
            on_capture=self._on_capture_hotkey,
            hotkey=self._config.get("hotkey", "ctrl+shift"),
        )

        # 系统托盘
        self._tray = TrayIcon(
            icon_path=self._get_icon_path(),
            auto_start=self._config.get("auto_start", False),
        )
        self._tray.settings_requested.connect(self._show_settings)
        self._tray.history_requested.connect(self._show_history)
        self._tray.reset_requested.connect(self._do_reset)
        self._tray.auto_start_changed.connect(self._set_auto_start)
        self._tray.about_requested.connect(self._show_about)
        self._tray.quit_requested.connect(self._quit)

        # 对话框引用（懒加载）
        self._settings_dialog = None
        self._history_dialog = None

        # 信号连接：QueuedConnection 提供事件循环缓冲
        self._capture_signal.connect(
            self._handle_capture, Qt.ConnectionType.QueuedConnection
        )
        self._text_received_signal.connect(
            self._process_text, Qt.ConnectionType.QueuedConnection
        )

    def start(self) -> None:
        """启动应用"""
        # 显示系统托盘
        self._tray.show()

        # 注册快捷键（优雅降级：失败不崩溃）
        try:
            self._hotkey_manager.start()
        except Exception as e:
            logger.error("快捷键注册失败，应用将继续运行但热键功能不可用: %s", e)
            self._toast.show_toast(
                "快捷键注册失败 | 请尝试以管理员运行",
                duration_ms=3000,
                is_error=True,
            )

        # 显示启动提示
        self._toast.show_toast(
            "FastDivider 已启动",
            duration_ms=2000,
        )

        logger.info("FastDivider 应用已启动，等待第一个数字...")

    def _get_icon_path(self) -> Path:
        """获取图标文件路径"""
        import sys

        if hasattr(sys, '_MEIPASS'):
            bundled_path = Path(sys._MEIPASS) / "resources" / "icon.ico"
            if bundled_path.exists():
                return bundled_path

        dev_path = Path(__file__).parent / "resources" / "icon.ico"
        if dev_path.exists():
            return dev_path

        logger.warning("未找到图标文件，将使用默认图标")
        return dev_path

    # --- 快捷键回调 -> 通过信号缓冲转移到独立处理 ---
    def _on_capture_hotkey(self) -> None:
        """快捷键回调（在轮询回调中执行，仅 emit 信号）"""
        self._capture_signal.emit()

    # --- 主线程处理 ---
    def _handle_capture(self) -> None:
        """触发获取选中文本（在主线程中执行）"""
        # 防重入：如果上一次获取操作还未完成，跳过本次
        if not self._capture_lock.acquire(blocking=False):
            logger.debug("获取操作正在进行中，跳过本次按键")
            return

        # 异步获取选中文本
        self._clipboard.get_selected_text(self._on_text_received)

    def _on_text_received(self, text: Optional[str]) -> None:
        """文本获取完成的回调"""
        self._capture_lock.release()

        if text is not None:
            self._text_received_signal.emit(text)
        else:
            self._text_received_signal.emit("")

    def _process_text(self, text: str) -> None:
        """处理获取到的文本（在主线程中通过 QueuedConnection 接收）"""
        if not text:
            self._show_error("获取选中文本失败")
            return

        # 解析数字
        number = parse_number(text)

        if number is None:
            self._show_error("无法识别数字")
            return

        # 根据当前状态处理
        if self._state == AppState.WAIT_FIRST_NUMBER:
            self._first_number = number
            self._state = AppState.WAIT_SECOND_NUMBER
            logger.info("已记录被除数: %s", number)

            display = format_number_display(number)
            self._toast.show_toast(
                f"已记录数字：{display}",
                duration_ms=int(self._config.get("toast_duration", 1) * 1000),
            )

        elif self._state == AppState.WAIT_SECOND_NUMBER:
            a = self._first_number
            b = number

            # 防御性检查：确保被除数已记录
            if a is None:
                self._show_error("状态异常，请重试")
                self._state = AppState.WAIT_FIRST_NUMBER
                self._first_number = None
                return

            # 检查除数为 0
            if b == 0:
                self._show_error("除数不能为 0")
                self._state = AppState.WAIT_FIRST_NUMBER
                self._first_number = None
                return

            # 计算结果
            result = a / b
            decimal_places = self._config.get("decimal_places", 2)

            # 格式化表达式
            expression = format_division(a, b, result, decimal_places)
            logger.info("计算结果: %s", expression)

            # 显示结果 Toast
            duration_ms = int(self._config.get("display_duration", 2) * 1000)
            self._toast.show_toast(expression, duration_ms=duration_ms, is_result=True)

            # 记录历史
            timestamp = datetime.now(timezone.utc).isoformat()
            self._history.add(expression, a, b, result, timestamp)

            # 重置状态，准备下一次计算
            self._state = AppState.WAIT_FIRST_NUMBER
            self._first_number = None

    def _do_reset(self) -> None:
        """托盘菜单触发重置"""
        self._state = AppState.WAIT_FIRST_NUMBER
        self._first_number = None
        logger.info("计算状态已重置")

        self._toast.show_toast(
            "计算状态已重置",
            duration_ms=int(self._config.get("toast_duration", 1) * 1000),
        )

    def _show_error(self, message: str) -> None:
        """显示错误提示 Toast"""
        self._toast.show_toast(
            message,
            duration_ms=1500,
            is_error=True,
        )

    # --- 对话框操作 ---
    def _show_settings(self) -> None:
        """显示设置对话框（复用已有实例，关闭后再打开只刷新配置值）"""
        from src.ui.settings_dialog import SettingsDialog

        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(
                self._config,
                self._hotkey_manager,
            )
            self._settings_dialog.accepted.connect(self._on_settings_saved)
        else:
            # 复用已有实例：刷新配置值以反映运行时变更
            self._settings_dialog._load_values()
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _on_settings_saved(self) -> None:
        """设置保存后更新 UI 配置"""
        self._toast.update_position(self._config.get("display_position", "bottom_right"))
        self._toast.update_theme(self._config.get("theme", "light"))
        self._toast.update_pin_mode(self._config.get("pin_mode", False))
        self._tray.update_auto_start(self._config.get("auto_start", False))
        logger.info("UI 配置已更新")

    def _show_history(self) -> None:
        """显示历史记录窗口"""
        from src.ui.history_dialog import HistoryDialog

        if self._history_dialog is None or not self._history_dialog.isVisible():
            self._history_dialog = HistoryDialog(self._history)
        else:
            self._history_dialog.refresh()
        self._history_dialog.show()
        self._history_dialog.raise_()
        self._history_dialog.activateWindow()

    def _set_auto_start(self, enabled: bool) -> None:
        """设置开机启动"""
        self._config.set("auto_start", enabled)
        self._manage_auto_start(enabled)
        self._tray.update_auto_start(enabled)

    def _manage_auto_start(self, enabled: bool) -> None:
        """管理 Windows 注册表开机启动项"""
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_WRITE,
            )

            if enabled:
                import sys
                exe_path = sys.executable if hasattr(sys, '_MEIPASS') else ""
                if exe_path:
                    winreg.SetValueEx(key, "FastDivider", 0, winreg.REG_SZ, exe_path)
                    logger.info("开机启动已启用")
                else:
                    logger.warning("无法确定 EXE 路径，开机启动设置失败")
            else:
                try:
                    winreg.DeleteValue(key, "FastDivider")
                    logger.info("开机启动已禁用")
                except FileNotFoundError:
                    pass

            winreg.CloseKey(key)
        except Exception as e:
            logger.error("开机启动设置失败: %s", e)

    def _show_about(self) -> None:
        """显示关于对话框"""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(
            None,
            "关于 FastDivider",
            "FastDivider 极速除法助手 v1.0\n\n"
            "连续选中数字进行快速除法计算。\n\n"
            "轻量、高效、开箱即用。",
        )

    def _quit(self) -> None:
        """退出应用"""
        logger.info("FastDivider 正在退出...")
        self._hotkey_manager.stop()
        self._tray.hide()
        self._app.quit()
