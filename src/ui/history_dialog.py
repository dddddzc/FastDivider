"""历史记录界面模块

提供历史记录查看窗口，支持：
- 按组别查看记录（下拉选择，默认选中 "默认" 组）
- 新增/删除自定义组别（"默认" 组不可删除）
- 勾选 "记录到特定组"：每次计算后弹窗选择组别（状态持久化）
- 批量勾选/全选记录后删除
- 批量勾选/全选记录后导出为 CSV 文件
"""

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QFileDialog, QLabel,
    QComboBox, QCheckBox, QInputDialog,
)
from PyQt6.QtCore import Qt

from src.core.config import ConfigManager
from src.core.history import HistoryManager, DEFAULT_GROUP_NAME, format_timestamp
from src.version import APP_NAME

logger = logging.getLogger(__name__)


class HistoryDialog(QDialog):
    """历史记录查看窗口

    支持按组浏览、新增/删除组、勾选"记录到特定组"。
    对话框复用：app.py 创建一次后通过 refresh() 刷新。
    """

    def __init__(
        self,
        history_manager: HistoryManager,
        config_manager: ConfigManager,
    ) -> None:
        super().__init__()
        self._history = history_manager
        self._config = config_manager

        self.setWindowTitle(f"{APP_NAME} 历史记录")
        self.setFixedSize(540, 650)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # 在下拉重建过程中静默信号，避免触发 _on_group_changed
        self._loading_groups = False
        # 在批量勾选/全选操作中静默 itemChanged 信号，避免循环
        self._updating_checks = False

        self._init_ui()
        self._reload_groups()
        self._load_entries()

    # --- UI 构建 ---
    def _init_ui(self) -> None:
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # 顶部：组别下拉 + 新增/删除按钮
        group_row = QHBoxLayout()
        group_row.setSpacing(8)

        group_row.addWidget(QLabel("组别："))
        self._group_combo = QComboBox()
        self._group_combo.setMinimumWidth(160)
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)
        group_row.addWidget(self._group_combo)

        add_group_btn = QPushButton("新增组别")
        add_group_btn.clicked.connect(self._add_group)
        group_row.addWidget(add_group_btn)

        del_group_btn = QPushButton("删除组别")
        del_group_btn.clicked.connect(self._delete_group)
        group_row.addWidget(del_group_btn)

        group_row.addStretch()
        layout.addLayout(group_row)

        # 勾选框：记录到特定组
        self._record_checkbox = QCheckBox("记录到特定组（每次计算后弹窗选择组别）")
        self._record_checkbox.setChecked(bool(self._config.get("record_to_group", False)))
        self._record_checkbox.toggled.connect(self._on_record_toggled)
        layout.addWidget(self._record_checkbox)

        # 统计标签
        self._stats_label = QLabel()
        layout.addWidget(self._stats_label)

        # 全选勾选框
        self._select_all_cb = QCheckBox("全选")
        self._select_all_cb.toggled.connect(self._on_select_all_toggled)
        layout.addWidget(self._select_all_cb)

        # 列表
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_widget.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list_widget)

        # 操作按钮
        btn_layout = QHBoxLayout()

        delete_btn = QPushButton("删除选中")
        delete_btn.clicked.connect(self._delete_selected)
        btn_layout.addWidget(delete_btn)

        export_btn = QPushButton("导出CSV")
        export_btn.clicked.connect(self._export_csv)
        btn_layout.addWidget(export_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    # --- 下拉与组别管理 ---
    def _reload_groups(self, keep_selection: Optional[str] = None) -> None:
        """重建组别下拉项

        Args:
            keep_selection: 尝试保持选中的组别；若该组不存在则回退 "默认"
        """
        self._loading_groups = True
        try:
            current = keep_selection
            if current is None:
                current = self._group_combo.currentText()
            groups = self._history.all_groups()
            self._group_combo.clear()
            self._group_combo.addItems(groups)

            # 恢复选中
            if current in groups:
                self._group_combo.setCurrentText(current)
            else:
                self._group_combo.setCurrentText(DEFAULT_GROUP_NAME)
        finally:
            self._loading_groups = False

    def _on_group_changed(self, _idx: int) -> None:
        """下拉切换组别时刷新列表（重建过程中静默）"""
        if self._loading_groups:
            return
        self._load_entries()

    def _add_group(self) -> None:
        """新增自定义组别"""
        name, ok = QInputDialog.getText(
            self,
            "新增组别",
            "请输入组别名称：",
            text="",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "提示", "组别名称不能为空")
            return
        if name == DEFAULT_GROUP_NAME:
            QMessageBox.warning(
                self, "提示",
                f"不能与默认组同名（{DEFAULT_GROUP_NAME}）",
            )
            return
        if self._history.add_group(name):
            self._reload_groups(keep_selection=name)
            QMessageBox.information(self, "提示", f"已创建组别：{name}")
        else:
            QMessageBox.warning(self, "提示", f"组别已存在或无效：{name}")

    def _delete_group(self) -> None:
        """删除自定义组别及其全部记录"""
        custom = self._history.custom_groups()
        if not custom:
            QMessageBox.information(self, "提示", "没有可删除的自定义组别")
            return

        name, ok = QInputDialog.getItem(
            self,
            "删除组别",
            "选择要删除的组别（将连同其所有记录一并删除）：",
            custom,
            0,
            editable=False,
        )
        if not ok:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除组别 \"{name}\"？\n该组别的所有记录将被一并清除，且不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        current_before = self._group_combo.currentText()
        if self._history.delete_group(name):
            # 若删除的是当前选中组，回退到 "默认"
            keep = None if name == current_before else current_before
            self._reload_groups(keep_selection=keep)
            self._load_entries()
            QMessageBox.information(self, "提示", f"已删除组别：{name}")
        else:
            QMessageBox.warning(self, "提示", f"删除失败：{name}")

    def _on_record_toggled(self, checked: bool) -> None:
        """勾选框状态变更：持久化到 config"""
        self._config.set("record_to_group", bool(checked))
        logger.info("记录到特定组: %s", checked)

    # --- 列表加载 ---
    def _current_group(self) -> str:
        """当前下拉选中的组别"""
        text = self._group_combo.currentText()
        return text if text else DEFAULT_GROUP_NAME

    def _load_entries(self) -> None:
        """加载当前组别的历史记录到列表（按时间倒序，最新在最上方）"""
        self._updating_checks = True
        try:
            self._list_widget.clear()
            group = self._current_group()
            # 按时间戳倒序：ISO 8601 UTC 字符串可字典序排序，reverse=True 使最新记录在最上方
            entries_with_idx = sorted(
                self._history.get_by_group_with_indices(group),
                key=lambda pair: pair[1].timestamp,
                reverse=True,
            )

            self._stats_label.setText(f"共 {len(entries_with_idx)} 条记录（{group}）")

            for idx, entry in entries_with_idx:
                local_ts = format_timestamp(entry.timestamp)
                item = QListWidgetItem(f"{entry.expression}    [{local_ts}]")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, idx)
                self._list_widget.addItem(item)

            # 重置全选状态
            self._select_all_cb.setChecked(False)

            # 选中第一条（最新的记录，位于列表顶部）
            if self._list_widget.count() > 0:
                self._list_widget.setCurrentRow(0)
        finally:
            self._updating_checks = False

    # --- 操作按钮槽 ---
    def _delete_selected(self) -> None:
        """删除勾选的历史记录"""
        indices = self._collect_checked_indices()
        if not indices:
            QMessageBox.information(self, "提示", "请先勾选要删除的记录")
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除选中的 {len(indices)} 条记录？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._history.delete_entries(indices)
            self._load_entries()

    def _export_csv(self) -> None:
        """导出勾选的历史记录为 CSV 文件"""
        indices = self._collect_checked_indices()
        if not indices:
            QMessageBox.information(self, "提示", "请先勾选要导出的记录")
            return
        group = self._current_group()
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出 CSV（{group}）",
            f"historys_{group}.csv",
            "CSV 文件 (*.csv)",
        )
        if path:
            try:
                decimal_places = int(self._config.get("decimal_places", 2))
                self._history.export_csv(Path(path), indices, decimal_places)
                QMessageBox.information(self, "提示", f"已导出到: {path}")
            except Exception as e:
                logger.error("导出失败: %s", e)
                QMessageBox.warning(self, "提示", "导出失败")

    def _collect_checked_indices(self) -> list[int]:
        """收集列表中所有勾选项的记录索引"""
        indices: list[int] = []
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                idx = item.data(Qt.ItemDataRole.UserRole)
                if idx is not None:
                    indices.append(int(idx))
        return indices

    def _on_select_all_toggled(self, checked: bool) -> None:
        """全选/取消全选"""
        if self._updating_checks:
            return
        self._updating_checks = True
        try:
            state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            for i in range(self._list_widget.count()):
                self._list_widget.item(i).setCheckState(state)
        finally:
            self._updating_checks = False

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """单个勾选状态变化时同步全选框"""
        if self._updating_checks:
            return
        self._updating_checks = True
        try:
            count = self._list_widget.count()
            if count == 0:
                self._select_all_cb.setChecked(False)
            else:
                all_checked = all(
                    self._list_widget.item(i).checkState() == Qt.CheckState.Checked
                    for i in range(count)
                )
                self._select_all_cb.setChecked(all_checked)
        finally:
            self._updating_checks = False

    def refresh(self) -> None:
        """刷新对话框：重建组别下拉并重新加载列表

        供 app.py 复用对话框时调用。
        """
        self._record_checkbox.setChecked(bool(self._config.get("record_to_group", False)))
        self._reload_groups()
        self._load_entries()
