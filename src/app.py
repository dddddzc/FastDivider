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

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal, Qt

from src.core.config import ConfigManager
from src.core.number_parser import parse_number, format_division, format_number_display
from src.core.clipboard_reader import ClipboardReader
from src.core.hotkey_manager import HotkeyManager
from src.core.history import HistoryManager
from src.core.updater import Updater, get_current_version
from src.ui.toast_window import ToastWindow
from src.ui.tray_icon import TrayIcon
from src.ui.update_dialog import UpdateDialog

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
        self._tray.check_update_requested.connect(self._check_update_manual)
        self._tray.about_requested.connect(self._show_about)
        self._tray.quit_requested.connect(self._quit)

        # 更新管理器
        self._updater = Updater()
        self._updater.update_available.connect(self._on_update_available)
        self._updater.no_update.connect(self._on_no_update)
        self._updater.error_occurred.connect(self._on_update_error)

        # 对话框引用（懒加载）
        self._settings_dialog = None
        self._history_dialog = None
        self._update_dialog = None

        # 更新检查模式标记
        self._update_check_silent = True

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
            QMessageBox.warning(
                None, "FastDivider",
                "快捷键注册失败\n\n请尝试以管理员身份运行本程序。",
            )

        # 显示启动提示
        self._toast.show_toast(
            "FastDivider 已启动",
            duration_ms=2000,
        )

        # 启动时自动检查更新（静默模式）
        self._check_update_silent()

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

        try:
            # 异步获取选中文本
            self._clipboard.get_selected_text(self._on_text_received)
        except Exception:
            self._capture_lock.release()
            raise

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

        QMessageBox.information(None, "FastDivider", "计算状态已重置")

    def _show_error(self, message: str) -> None:
        """显示错误提示弹窗"""
        QMessageBox.warning(None, "FastDivider", message)

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

    # --- 更新检测 ---
    def _check_update_silent(self) -> None:
        """启动时静默检查更新（有新版本才提示）"""
        logger.info("启动时静默检查更新...")
        self._update_check_silent = True
        self._updater.check_for_updates()

    def _check_update_manual(self) -> None:
        """手动检查更新（始终显示结果）"""
        logger.info("用户手动检查更新...")
        self._update_check_silent = False
        if not self._updater.check_for_updates():
            QMessageBox.information(
                None, "FastDivider",
                "请稍后再试（距离上次检查时间太近）",
            )

    def _on_update_available(self, current_version: str, latest_version: str) -> None:
        """发现新版本，弹窗确认并展示下载进度"""
        logger.info("发现新版本: %s → %s", current_version, latest_version)

        self._update_dialog = UpdateDialog(current_version, latest_version)
        self._update_dialog.accepted.connect(
            lambda: self._start_update_download(self._update_dialog)
        )

        # 模态对话框，阻塞用户操作直到下载完成或取消
        self._update_dialog.exec()

    def _start_update_download(self, dialog: UpdateDialog) -> None:
        """开始下载并连接进度信号到对话框"""
        # 连接下载进度到对话框
        self._updater.download_progress.connect(dialog.update_progress)
        self._updater.download_complete.connect(dialog.on_download_complete)
        self._updater.error_occurred.connect(dialog.on_download_error)

        # 下载完成后自动安装重启
        self._updater.download_complete.connect(
            lambda: self._do_update_restart(dialog)
        )

        self._updater.start_download()

    def _do_update_restart(self, dialog: UpdateDialog) -> None:
        """下载完成，短暂延迟后安装并重启"""
        from PyQt6.QtCore import QTimer
        # 给用户 0.5s 看到"安装完成"，然后执行替换重启
        QTimer.singleShot(500, self._updater.apply_update_and_restart)

    def _on_no_update(self) -> None:
        """已是最新版本（静默模式不提示）"""
        logger.info("已是最新版本")
        if not self._update_check_silent:
            QMessageBox.information(None, "FastDivider", "已是最新版本 ✓")

    def _on_update_error(self, error_msg: str) -> None:
        """更新检查出错（静默模式不提示）"""
        logger.error("更新检查出错: %s", error_msg)
        if not self._update_check_silent:
            self._show_update_error_with_guide(error_msg)

    def _show_update_error_with_guide(self, error_msg: str) -> None:
        """显示更新错误弹窗，并附带手动下载指引"""
        releases_url = "https://github.com/dddddzc/FastDivider/releases"

        msg_box = QMessageBox()
        msg_box.setWindowTitle("更新失败")
        msg_box.setIcon(QMessageBox.Icon.Warning)

        guide_text = (
            f"<p>{error_msg}</p>"
            f"<p><b>您可以手动下载最新版本：</b><br>"
            f"<a href='{releases_url}'>{releases_url}</a>"
            f"&nbsp;&nbsp;<i>（Ctrl+单击 打开链接）</i></p>"
            f"<hr>"
            f"<p><b>手动更新步骤：</b></p>"
            f"<ol>"
            f"<li>在 Releases 页面下载最新版本的 <code>FastDivider-vX.X.X.zip</code></li>"
            f"<li>解压 ZIP 文件</li>"
            f"<li>退出当前运行的 FastDivider（右键托盘图标 → 退出）</li>"
            f"<li>用解压出的 <code>FastDivider.exe</code> 替换旧版本文件</li>"
            f"<li>启动新版本即可</li>"
            f"</ol>"
        )

        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(guide_text)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def _show_about(self) -> None:
        """显示关于对话框"""
        version = get_current_version()
        QMessageBox.about(
            None,
            "关于 FastDivider",
            f"FastDivider 极速除法助手 v{version}\n\n"
            "连续选中数字进行快速除法计算。\n\n"
            "轻量、高效、开箱即用。",
        )

    def _quit(self) -> None:
        """退出应用"""
        logger.info("FastDivider 正在退出...")
        self._hotkey_manager.stop()
        self._tray.hide()
        self._app.quit()
