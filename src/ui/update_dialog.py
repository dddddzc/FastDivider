"""更新对话框模块

模态对话框，显示版本信息和下载进度。
下载完成后自动安装并重启。
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSlot

from src.version import APP_NAME, APP_EXE_NAME, GITHUB_RELEASES_URL, get_zip_asset_name

logger = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """更新对话框

    三阶段流程：
    1. 确认更新 — 显示版本信息，「立即更新」/「稍后再说」
    2. 下载中   — 进度条 + 取消按钮
    3. 安装中   — 下载完成，准备替换重启（0.5s 后自动执行）

    对话框为模态，下载期间阻止用户操作主应用。
    """

    def __init__(self, current_version: str, latest_version: str) -> None:
        super().__init__()
        self._current_version = current_version
        self._latest_version = latest_version
        self._download_url: str = ""
        self._cancelled = False

        self.setWindowTitle("发现新版本")
        self.setFixedSize(420, 240)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self._init_ui()
        self._show_confirm_phase()

    def _init_ui(self) -> None:
        """初始化 UI 组件"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # 标题
        self._title_label = QLabel()
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        # 说明信息
        self._info_label = QLabel()
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setWordWrap(True)
        self._info_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self._info_label)

        layout.addStretch()

        # 进度条（下载阶段显示）
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("下载中... %p%")
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

        # 状态文字
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        self._status_label.hide()
        layout.addWidget(self._status_label)

        # 按钮区
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._cancel_btn = QPushButton("稍后再说")
        self._cancel_btn.setFixedWidth(100)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        btn_layout.addSpacing(12)

        self._update_btn = QPushButton("立即更新")
        self._update_btn.setFixedWidth(110)
        self._update_btn.setDefault(True)
        self._update_btn.clicked.connect(self._on_start_update)
        btn_layout.addWidget(self._update_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _show_confirm_phase(self) -> None:
        """第一阶段：确认更新"""
        self._title_label.setText(
            f"<h3 style='color:#333;'>发现新版本 v{self._latest_version}</h3>"
        )
        self._info_label.setText(
            f"当前版本：v{self._current_version} → 最新版本：v{self._latest_version}"
        )

    def _show_download_phase(self) -> None:
        """第二阶段：下载中"""
        self._title_label.setText(
            f"<h3 style='color:#333;'>正在下载 v{self._latest_version}</h3>"
        )
        self._info_label.setText("正在从 GitHub 下载更新包...")
        self._info_label.show()
        self._progress_bar.show()
        self._status_label.show()
        self._update_btn.hide()
        self._cancel_btn.setText("取消")
        self.setWindowTitle("正在下载更新...")

    @pyqtSlot(int)
    def update_progress(self, pct: int) -> None:
        """更新进度条（连接到 Updater.download_progress）"""
        self._progress_bar.setValue(pct)
        self._status_label.setText(f"已下载 {pct}%")

    @pyqtSlot()
    def on_download_complete(self) -> None:
        """下载完成回调"""
        if self._cancelled:
            return
        self._progress_bar.setValue(100)
        self._title_label.setText("<h3 style='color:#333;'>安装完成</h3>")
        self._info_label.setText("正在替换旧版本并重启应用...")
        self._progress_bar.hide()
        self._status_label.setText("应用即将重启")
        self._cancel_btn.hide()
        self.setWindowTitle("更新完成")

    @pyqtSlot(str)
    def on_download_error(self, error_msg: str) -> None:
        """下载出错回调"""
        if self._cancelled:
            return
        self._title_label.setText("<h3 style='color:#c00;'>下载失败</h3>")
        self._info_label.setText(error_msg)
        self._progress_bar.hide()
        self._status_label.hide()
        self._cancel_btn.setText("关闭")
        self._cancel_btn.show()
        self.setWindowTitle("更新失败")

        # 弹出手动下载指引
        self._show_manual_download_guide()

    def _show_manual_download_guide(self) -> None:
        """显示手动下载指引弹窗

        包含 GitHub Releases 链接和手动更新步骤。
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("手动更新指引")
        msg_box.setIcon(QMessageBox.Icon.Information)

        guide_text = (
            f"<p>自动下载失败，您可以手动下载最新版本：</p>"
            f"<p><b>下载地址：</b><br>"
            f"<a href='{GITHUB_RELEASES_URL}'>{GITHUB_RELEASES_URL}</a>"
            f"&nbsp;&nbsp;<i>（点击打开）</i></p>"
            f"<hr>"
            f"<p><b>手动更新步骤：</b></p>"
            f"<ol>"
            f"<li>在 Releases 页面下载最新版本的 <code>{get_zip_asset_name()}</code></li>"
            f"<li>解压 ZIP 文件</li>"
            f"<li>退出当前运行的 {APP_NAME}（右键托盘图标 → 退出）</li>"
            f"<li>用解压出的 <code>{APP_EXE_NAME}</code> 替换旧版本文件</li>"
            f"<li>启动新版本即可</li>"
            f"</ol>"
        )

        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(guide_text)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def _on_start_update(self) -> None:
        """用户点击「立即更新」"""
        self._show_download_phase()
        self.accepted.emit()

    def reject(self) -> None:
        """用户取消"""
        self._cancelled = True
        super().reject()

    # Properties for direct access
    @property
    def cancelled(self) -> bool:
        return self._cancelled
