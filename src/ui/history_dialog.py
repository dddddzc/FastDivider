"""历史记录界面模块

提供历史记录查看窗口，支持：
- 查看最近 100 条记录
- 复制单条记录
- 清空全部记录
- 导出 TXT 文件
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QFileDialog, QLabel,
)
from PyQt6.QtCore import Qt

from src.core.history import HistoryManager

logger = logging.getLogger(__name__)


def _format_timestamp(ts_str: str) -> str:
    """将 ISO UTC 时间戳转换为本地可读格式

    Args:
        ts_str: ISO 8601 UTC 时间戳，如 "2026-06-14T08:30:00+00:00"

    Returns:
        本地可读格式，如 "2026-06-14 16:30:00"；解析失败则原样返回
    """
    try:
        dt = datetime.fromisoformat(ts_str).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts_str


class HistoryDialog(QDialog):
    """历史记录查看窗口"""

    def __init__(self, history_manager: HistoryManager) -> None:
        super().__init__()
        self._history = history_manager

        self.setWindowTitle("FastDivider 历史记录")
        self.setFixedSize(500, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self._init_ui()
        self._load_entries()

    def _init_ui(self) -> None:
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题和统计
        self._stats_label = QLabel()
        layout.addWidget(self._stats_label)

        # 列表
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        layout.addWidget(self._list_widget)

        # 操作按钮
        btn_layout = QHBoxLayout()

        copy_btn = QPushButton("复制选中")
        copy_btn.clicked.connect(self._copy_selected)
        btn_layout.addWidget(copy_btn)

        clear_btn = QPushButton("清空全部")
        clear_btn.clicked.connect(self._clear_all)
        btn_layout.addWidget(clear_btn)

        export_btn = QPushButton("导出 TXT")
        export_btn.clicked.connect(self._export_txt)
        btn_layout.addWidget(export_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _load_entries(self) -> None:
        """加载历史记录到列表"""
        self._list_widget.clear()
        entries = self._history.get_all()

        self._stats_label.setText(f"共 {len(entries)} 条记录")

        for entry in entries:
            local_ts = _format_timestamp(entry.timestamp)
            item = QListWidgetItem(f"{entry.expression}    [{local_ts}]")
            item.setData(Qt.ItemDataRole.UserRole, entry.expression)
            self._list_widget.addItem(item)

        # 选中最后一条（最近的记录）
        if self._list_widget.count() > 0:
            self._list_widget.setCurrentRow(self._list_widget.count() - 1)

    def _copy_selected(self) -> None:
        """复制选中的记录到剪贴板"""
        current = self._list_widget.currentItem()
        if current is None:
            QMessageBox.information(self, "提示", "请先选择一条记录")
            return

        expression = current.data(Qt.ItemDataRole.UserRole)
        try:
            import pyperclip
            pyperclip.copy(expression)
            QMessageBox.information(self, "提示", f"已复制: {expression}")
        except Exception as e:
            logger.error("复制失败: %s", e)
            QMessageBox.warning(self, "提示", "复制失败")

    def _clear_all(self) -> None:
        """清空全部历史记录"""
        reply = QMessageBox.question(
            self,
            "确认",
            "确定要清空全部历史记录？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._history.clear()
            self._load_entries()

    def _export_txt(self) -> None:
        """导出历史记录为 TXT 文件"""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出历史记录",
            "FastDivider_history.txt",
            "文本文件 (*.txt)",
        )
        if path:
            try:
                self._history.export_txt(Path(path))
                QMessageBox.information(self, "提示", f"已导出到: {path}")
            except Exception as e:
                logger.error("导出失败: %s", e)
                QMessageBox.warning(self, "提示", "导出失败")

    def refresh(self) -> None:
        """刷新列表内容"""
        self._load_entries()
