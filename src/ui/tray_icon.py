"""系统托盘图标模块

负责系统托盘图标显示和右键菜单管理。
右键菜单包含：设置、历史记录、重置状态、开机启动、关于、退出。
"""

import logging
from pathlib import Path

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class TrayIcon(QObject):
    """系统托盘图标管理器

    提供右键菜单操作入口，通过信号将操作传递给主应用。
    """

    # 信号定义
    settings_requested = pyqtSignal()
    history_requested = pyqtSignal()
    reset_requested = pyqtSignal()
    auto_start_changed = pyqtSignal(bool)
    about_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(
        self,
        icon_path: Path,
        auto_start: bool = False,
    ) -> None:
        super().__init__()
        self._icon_path = icon_path
        self._auto_start = auto_start

        self._tray = QSystemTrayIcon()
        self._menu = QMenu()

        self._init_icon()
        self._init_menu()

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

    def _init_icon(self) -> None:
        """初始化托盘图标"""
        icon = QIcon(str(self._icon_path))
        if icon.isNull():
            logger.warning("图标文件加载失败: %s，使用默认图标", self._icon_path)
            # 使用 Qt 内置图标作为备用
            from PyQt6.QtWidgets import QApplication
            icon = QApplication.style().standardIcon(
                QApplication.style().StandardPixmap.SP_CommandLink
            )
        self._tray.setIcon(icon)
        self._tray.setToolTip("FastDivider - 极速除法助手")

    def _init_menu(self) -> None:
        """初始化右键菜单"""
        # 设置
        settings_action = QAction("⚙ 设置", self._menu)
        settings_action.triggered.connect(self.settings_requested.emit)
        self._menu.addAction(settings_action)

        # 历史记录
        history_action = QAction("📋 历史记录", self._menu)
        history_action.triggered.connect(self.history_requested.emit)
        self._menu.addAction(history_action)

        self._menu.addSeparator()

        # 重置状态
        reset_action = QAction("🔄 重置状态", self._menu)
        reset_action.triggered.connect(self.reset_requested.emit)
        self._menu.addAction(reset_action)

        # 开机启动
        self._auto_start_action = QAction("🚀 开机启动", self._menu)
        self._auto_start_action.setCheckable(True)
        self._auto_start_action.setChecked(self._auto_start)
        self._auto_start_action.triggered.connect(self._on_auto_start_toggled)
        self._menu.addAction(self._auto_start_action)

        self._menu.addSeparator()

        # 关于
        about_action = QAction("ℹ 关于", self._menu)
        about_action.triggered.connect(self.about_requested.emit)
        self._menu.addAction(about_action)

        # 退出
        quit_action = QAction("❌ 退出", self._menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(quit_action)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """托盘图标被点击"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.settings_requested.emit()

    def _on_auto_start_toggled(self, checked: bool) -> None:
        """开机启动开关切换"""
        self._auto_start = checked
        self.auto_start_changed.emit(checked)
        logger.info("开机启动设置: %s", checked)

    def show(self) -> None:
        """显示托盘图标"""
        self._tray.show()
        logger.info("系统托盘图标已显示")

    def hide(self) -> None:
        """隐藏托盘图标"""
        self._tray.hide()

    def update_auto_start(self, enabled: bool) -> None:
        """更新开机启动复选框状态"""
        self._auto_start = enabled
        self._auto_start_action.setChecked(enabled)

    def show_message(self, title: str, message: str) -> None:
        """显示托盘气泡消息"""
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 2000)
