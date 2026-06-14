"""设置界面模块 - Snipaste 风格

左侧分类导航 + 右侧内容区。
快捷键设置采用按键录制方式：点击按钮后自动捕获按键组合，
不需要手动输入字符串。
"""

import logging

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QSpinBox, QCheckBox, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QStackedWidget,
    QFrame, QWidget, QMessageBox,
)
from PyQt6.QtCore import Qt, QSize, QTimer

from src.core.config import ConfigManager

logger = logging.getLogger(__name__)


class HotkeyRecordButton(QPushButton):
    """按键录制按钮

    点击后进入录制状态，实时显示用户已按下的键组合。
    所有键释放后自动完成录制；10 秒未操作自动取消。
    """

    RECORDING_TIMEOUT_MS = 10000

    def __init__(self) -> None:
        super().__init__("点击录制快捷键")
        self._hotkey_text = ""
        self._is_recording = False
        self._hotkey_manager = None
        self._elapsed_ms = 0

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)

        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._start_recording)
        self._poll_timer.timeout.connect(self._check_recording_result)

    def hotkey_text(self) -> str:
        return self._hotkey_text

    def set_hotkey_text(self, text: str) -> None:
        self._hotkey_text = text
        self.setText(text if text else "点击录制快捷键")

    def set_hotkey_manager(self, manager) -> None:
        self._hotkey_manager = manager

    def _start_recording(self) -> None:
        if self._is_recording or self._hotkey_manager is None:
            return

        self._is_recording = True
        self._elapsed_ms = 0
        self.setText("请按下快捷键... (按完即完成)")
        self.setEnabled(False)
        self._hotkey_manager.start_recording()
        self._poll_timer.start()

    def _check_recording_result(self) -> None:
        if self._hotkey_manager is None:
            self._cancel_recording()
            return

        self._elapsed_ms += self._poll_timer.interval()
        if self._elapsed_ms >= self.RECORDING_TIMEOUT_MS:
            logger.info("按键录制超时，取消")
            self._hotkey_manager.cancel_recording()
            self._poll_timer.stop()
            self._is_recording = False
            self.setEnabled(True)
            # 显示超时反馈，2 秒后恢复为默认/旧文本
            self.setText("录制超时，请重试")
            restore_text = self._hotkey_text if self._hotkey_text else "点击录制快捷键"
            QTimer.singleShot(2000, lambda: self.setText(restore_text))
            return

        partial = self._hotkey_manager.get_partial_recording()
        if partial:
            self.setText(f"录制中: {partial}")

        if self._hotkey_manager.is_recording_done():
            result = self._hotkey_manager.get_recorded_hotkey()
            self._poll_timer.stop()
            self._is_recording = False
            self.setEnabled(True)

            if result:
                self._hotkey_text = result
                self.setText(result)
                logger.info("按键录制结果: %s", result)
            else:
                self.setText("点击录制快捷键")
                logger.info("按键录制未获取到结果")

    def _cancel_recording(self) -> None:
        self._poll_timer.stop()
        self._is_recording = False
        self.setEnabled(True)
        if self._hotkey_text:
            self.setText(self._hotkey_text)
        else:
            self.setText("点击录制快捷键")


class SettingsDialog(QDialog):
    """Snipaste 风格设置对话框

    左侧导航列表 + 右侧内容区。
    快捷键设置使用按键录制按钮，不需要手动输入。
    """

    POSITION_OPTIONS = {
        "屏幕右下角": "bottom_right",
        "屏幕中央": "center",
        "鼠标附近": "mouse_near",
    }

    NAV_ITEMS = ["快捷键", "显示", "通用"]

    def __init__(
        self,
        config: ConfigManager,
        hotkey_manager=None,
    ) -> None:
        super().__init__()
        self._config = config
        self._hotkey_manager = hotkey_manager

        self.setWindowTitle("FastDivider 设置")
        self.setMinimumSize(520, 400)
        self.setMaximumSize(600, 500)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self._init_ui()
        self._load_values()

    def _init_ui(self) -> None:
        """初始化 UI - 左侧导航 + 右侧内容区"""
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # --- 左侧导航 ---
        nav_frame = QFrame()
        nav_frame.setFixedWidth(120)
        nav_frame.setObjectName("navFrame")
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(8, 12, 8, 12)
        nav_layout.setSpacing(4)

        from PyQt6.QtGui import QFont

        title_label = QLabel("FastDivider")
        title_font = QFont()
        title_font.setFamily("Segoe UI")
        title_font.setPointSize(11)
        title_font.setWeight(QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(title_label)
        nav_layout.addSpacing(8)

        self._nav_list = QListWidget()
        self._nav_list.setObjectName("navList")
        self._nav_list.setFixedHeight(120)
        self._nav_list.setSpacing(2)
        self._nav_list.setCurrentRow(0)
        for item_text in self.NAV_ITEMS:
            item = QListWidgetItem(item_text)
            item.setSizeHint(QSize(0, 32))
            self._nav_list.addItem(item)
        nav_layout.addWidget(self._nav_list)
        nav_layout.addStretch()

        ver_label = QLabel("v1.0")
        ver_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_label.setObjectName("verLabel")
        nav_layout.addWidget(ver_label)
        main_layout.addWidget(nav_frame)

        # --- 分隔线 ---
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setObjectName("separator")
        main_layout.addWidget(separator)

        # --- 右侧内容区 ---
        content_frame = QFrame()
        content_frame.setObjectName("contentFrame")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(12)

        self._stacked_widget = QStackedWidget()
        self._nav_list.currentRowChanged.connect(
            self._stacked_widget.setCurrentIndex
        )
        self._init_hotkey_page()
        self._init_display_page()
        self._init_general_page()
        content_layout.addWidget(self._stacked_widget)

        # --- 底部按钮 ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        reset_btn = QPushButton("恢复默认")
        reset_btn.setObjectName("resetBtn")
        reset_btn.setFixedWidth(80)
        reset_btn.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(reset_btn)

        btn_layout.addSpacing(8)

        save_btn = QPushButton("保存并关闭")
        save_btn.setObjectName("saveBtn")
        save_btn.setFixedWidth(100)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.setFixedWidth(60)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        content_layout.addLayout(btn_layout)
        main_layout.addWidget(content_frame)

        self._apply_style()

    def _init_hotkey_page(self) -> None:
        """快捷键设置页 - 单个按键录制按钮"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        from PyQt6.QtGui import QFont

        header = QLabel("快捷键设置")
        header.setObjectName("pageHeader")
        layout.addWidget(header)

        desc = QLabel("点击下方按钮，然后按下你想要的快捷键。\n应用会自动识别按键组合，无需手动输入。")
        desc.setObjectName("pageDesc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(14)

        self._hotkey_record_btn = HotkeyRecordButton()
        self._hotkey_record_btn.set_hotkey_manager(self._hotkey_manager)
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self._hotkey_record_btn)
        hotkey_row.addStretch()
        form.addRow("快捷键（记录 / 计算）:", hotkey_row)

        layout.addLayout(form)

        hint = QLabel("提示：录制时请避免与系统快捷键冲突。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()
        self._stacked_widget.addWidget(page)

    def _init_display_page(self) -> None:
        """显示设置页"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        header = QLabel("显示设置")
        header.setObjectName("pageHeader")
        layout.addWidget(header)

        desc = QLabel("控制 Toast 的显示位置、持续时间和数值精度。")
        desc.setObjectName("pageDesc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(10)

        self._position_combo = QComboBox()
        self._position_combo.addItems(list(self.POSITION_OPTIONS.keys()))
        self._position_combo.setFixedWidth(200)
        form.addRow("结果显示位置:", self._position_combo)

        self._duration_combo = QComboBox()
        for d in [0.5, 1, 2, 3, 5]:
            self._duration_combo.addItem(f"{d} 秒", d)
        self._duration_combo.setFixedWidth(200)
        form.addRow("结果显示时长:", self._duration_combo)

        self._toast_duration_combo = QComboBox()
        for d in [0.5, 1, 2, 3, 5]:
            self._toast_duration_combo.addItem(f"{d} 秒", d)
        self._toast_duration_combo.setFixedWidth(200)
        form.addRow("提示显示时长:", self._toast_duration_combo)

        self._pin_mode_check = QCheckBox("计算结果长期悬浮（可手动关闭）")
        form.addRow(self._pin_mode_check)

        self._decimal_spin = QSpinBox()
        self._decimal_spin.setRange(0, 9)
        self._decimal_spin.setFixedWidth(200)
        form.addRow("小数位数:", self._decimal_spin)

        layout.addLayout(form)
        layout.addStretch()
        self._stacked_widget.addWidget(page)

    def _init_general_page(self) -> None:
        """通用设置页"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        header = QLabel("通用设置")
        header.setObjectName("pageHeader")
        layout.addWidget(header)

        desc = QLabel("开机启动和界面外观偏好。")
        desc.setObjectName("pageDesc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(10)

        self._auto_start_check = QCheckBox("Windows 开机自动启动")
        form.addRow(self._auto_start_check)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["浅色", "深色"])
        self._theme_combo.setFixedWidth(200)
        form.addRow("主题模式:", self._theme_combo)

        layout.addLayout(form)
        layout.addStretch()
        self._stacked_widget.addWidget(page)

    _LIGHT_STYLE = """
        QDialog { background-color: #f5f5f5; }
        #navFrame { background-color: #e8e8e8; border: none; }
        #navList { background-color: #e8e8e8; border: none; outline: none; font-family: "Segoe UI"; font-size: 13px; padding: 0; }
        #navList::item { padding: 6px 8px; border-radius: 4px; color: #555; }
        #navList::item:selected { background-color: #d0d0d0; color: #222; font-weight: bold; }
        #navList::item:hover { background-color: #d8d8d8; }
        #separator { color: #ccc; max-width: 1px; }
        #contentFrame { background-color: #f5f5f5; border: none; }
        #pageHeader { font-family: "Segoe UI"; font-size: 14px; font-weight: bold; color: #333; padding-bottom: 4px; }
        #pageDesc { font-family: "Segoe UI"; font-size: 12px; color: #888; padding-bottom: 2px; }
        #hintLabel { font-family: "Segoe UI"; font-size: 11px; color: #999; }
        #verLabel { font-family: "Segoe UI"; font-size: 10px; color: #aaa; }
        QPushButton { font-family: "Segoe UI"; font-size: 13px; padding: 6px 12px; border: 1px solid #ccc; border-radius: 4px; background-color: #fff; color: #555; }
        QPushButton:hover { background-color: #e8e8e8; }
        QPushButton:disabled { background-color: #f0f0f0; color: #aaa; border-color: #ddd; }
        #saveBtn { background-color: #4682C8; color: #fff; border-color: #4682C8; font-weight: bold; }
        #saveBtn:hover { background-color: #3a6fb5; }
        #resetBtn { color: #888; }
        #cancelBtn { color: #888; }
        QComboBox, QSpinBox { font-family: "Segoe UI"; font-size: 13px; padding: 4px 8px; border: 1px solid #ccc; border-radius: 4px; background-color: #fff; color: #555; }
        QComboBox:focus, QSpinBox:focus { border-color: #4682C8; }
        QCheckBox { font-family: "Segoe UI"; font-size: 13px; spacing: 6px; color: #555; }
        QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 1px solid #ccc; background-color: #fff; }
        QCheckBox::indicator:checked { background-color: #4682C8; border-color: #4682C8; }
        QLabel { font-family: "Segoe UI"; }
    """

    _DARK_STYLE = """
        QDialog { background-color: #2b2b30; }
        #navFrame { background-color: #35353a; border: none; }
        #navList { background-color: #35353a; border: none; outline: none; font-family: "Segoe UI"; font-size: 13px; padding: 0; }
        #navList::item { padding: 6px 8px; border-radius: 4px; color: #ccc; }
        #navList::item:selected { background-color: #45454a; color: #eee; font-weight: bold; }
        #navList::item:hover { background-color: #40404a; }
        #separator { color: #555; max-width: 1px; }
        #contentFrame { background-color: #2b2b30; border: none; }
        #pageHeader { font-family: "Segoe UI"; font-size: 14px; font-weight: bold; color: #e0e0e0; padding-bottom: 4px; }
        #pageDesc { font-family: "Segoe UI"; font-size: 12px; color: #888; padding-bottom: 2px; }
        #hintLabel { font-family: "Segoe UI"; font-size: 11px; color: #777; }
        #verLabel { font-family: "Segoe UI"; font-size: 10px; color: #666; }
        QPushButton { font-family: "Segoe UI"; font-size: 13px; padding: 6px 12px; border: 1px solid #555; border-radius: 4px; background-color: #40404a; color: #ccc; }
        QPushButton:hover { background-color: #4a4a50; }
        QPushButton:disabled { background-color: #35353a; color: #666; border-color: #444; }
        #saveBtn { background-color: #4682C8; color: #fff; border-color: #4682C8; font-weight: bold; }
        #saveBtn:hover { background-color: #3a6fb5; }
        #resetBtn { color: #888; }
        #cancelBtn { color: #888; }
        QComboBox, QSpinBox { font-family: "Segoe UI"; font-size: 13px; padding: 4px 8px; border: 1px solid #555; border-radius: 4px; background-color: #40404a; color: #ccc; }
        QComboBox:focus, QSpinBox:focus { border-color: #4682C8; }
        QCheckBox { font-family: "Segoe UI"; font-size: 13px; spacing: 6px; color: #ccc; }
        QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 1px solid #555; background-color: #40404a; }
        QCheckBox::indicator:checked { background-color: #4682C8; border-color: #4682C8; }
        QLabel { font-family: "Segoe UI"; }
    """

    def _apply_style(self) -> None:
        """根据当前主题应用样式"""
        theme = self._config.get("theme", "light")
        if theme == "dark":
            self.setStyleSheet(self._DARK_STYLE)
        else:
            self.setStyleSheet(self._LIGHT_STYLE)

    def _load_values(self) -> None:
        """从配置加载当前值"""
        self._hotkey_record_btn.set_hotkey_text(self._config.get("hotkey", "ctrl+shift"))

        position = self._config.get("display_position", "bottom_right")
        for display_name, value in self.POSITION_OPTIONS.items():
            if value == position:
                self._position_combo.setCurrentText(display_name)
                break

        duration = self._config.get("display_duration", 2)
        for i in range(self._duration_combo.count()):
            if self._duration_combo.itemData(i) == duration:
                self._duration_combo.setCurrentIndex(i)
                break

        toast_duration = self._config.get("toast_duration", 1)
        for i in range(self._toast_duration_combo.count()):
            if self._toast_duration_combo.itemData(i) == toast_duration:
                self._toast_duration_combo.setCurrentIndex(i)
                break

        decimal_val = self._config.get("decimal_places", 2)
        self._decimal_spin.setValue(decimal_val)
        self._auto_start_check.setChecked(self._config.get("auto_start", False))
        self._pin_mode_check.setChecked(self._config.get("pin_mode", False))

        theme = self._config.get("theme", "light")
        self._theme_combo.setCurrentIndex(0 if theme == "light" else 1)

    def _save_settings(self) -> None:
        """保存设置"""
        from src.core.hotkey_manager import HotkeyManager

        hotkey = self._hotkey_record_btn.hotkey_text().strip().lower()

        if not hotkey:
            QMessageBox.warning(self, "提示", "请先录制快捷键\n点击按钮后按下你想要的按键")
            return

        if not HotkeyManager.validate_hotkey(hotkey):
            QMessageBox.warning(self, "提示", f"快捷键格式无效: {hotkey}")
            return

        self._config.set("hotkey", hotkey)
        self._config.set("display_position", self.POSITION_OPTIONS[self._position_combo.currentText()])
        self._config.set("display_duration", self._duration_combo.currentData())
        self._config.set("toast_duration", self._toast_duration_combo.currentData())
        self._config.set("decimal_places", self._decimal_spin.value())
        self._config.set("auto_start", self._auto_start_check.isChecked())
        self._config.set("pin_mode", self._pin_mode_check.isChecked())
        self._config.set("theme", "light" if self._theme_combo.currentIndex() == 0 else "dark")

        logger.info("设置已保存")

        if self._hotkey_manager:
            self._hotkey_manager.update_hotkey(hotkey)

        self.accept()

    def _reset_defaults(self) -> None:
        """恢复默认设置"""
        self._config.reset_to_defaults()
        self._load_values()

        # 更新运行中的热键管理器
        if self._hotkey_manager:
            from src.core.config import DEFAULT_CONFIG
            self._hotkey_manager.update_hotkey(DEFAULT_CONFIG["hotkey"])

        logger.info("设置已恢复为默认值")
        self.accept()
