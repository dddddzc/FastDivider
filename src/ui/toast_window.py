"""Toast 显示窗口模块

负责以半透明无边框 Toast 的形式显示结果和提示信息。
Toast 不抢焦点、不影响当前输入，自动在指定时间后消失。

支持两种模式：
- 定时模式：显示指定时间后自动淡出消失（默认）
- 悬浮模式：结果窗口长期停留，带关闭按钮，用户手动关闭
  仅对计算结果生效，普通提示（如"已记录数字"）仍自动消失

注意：不使用 QGraphicsDropShadowEffect，因为与 WA_TranslucentBackground
组合在 Windows 上会导致窗口渲染问题。阴影效果通过 paintEvent 手动绘制。
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QRect
from PyQt6.QtGui import QPainter, QColor, QCursor, QFont, QPainterPath, QPaintEvent

logger = logging.getLogger(__name__)

# Toast 样式常量
TOAST_BORDER_RADIUS = 12
TOAST_MIN_WIDTH = 200
TOAST_MIN_HEIGHT = 60
TOAST_OPACITY = 0.92
TOAST_SHADOW_OFFSET = 4
TOAST_SHADOW_RADIUS = 12
TOAST_SHADOW_COLOR = QColor(0, 0, 0, 40)

# 悬浮模式下的关闭按钮样式
PIN_CLOSE_BTN_SIZE = 20


class ToastWindow(QWidget):
    """半透明无边框 Toast 窗口

    显示在屏幕指定位置，不抢焦点，支持定时消失或长期悬浮。
    支持三种显示位置：鼠标附近、屏幕中央、屏幕右下角。

    阴影通过 paintEvent 手动绘制，避免 QGraphicsDropShadowEffect
    与 WA_TranslucentBackground 的兼容性问题。
    """

    # 主题配色
    LIGHT_BG = QColor(245, 245, 250, int(255 * TOAST_OPACITY))
    LIGHT_TEXT = QColor(40, 40, 50)
    DARK_BG_COLOR = QColor(30, 30, 40, int(255 * TOAST_OPACITY))
    DARK_TEXT = QColor(240, 240, 250)
    LIGHT_BORDER = QColor(220, 220, 230, 150)
    DARK_BORDER = QColor(60, 60, 70, 150)

    def __init__(
        self,
        display_position: str = "bottom_right",
        theme: str = "light",
        pin_mode: bool = False,
    ) -> None:
        super().__init__()
        self._position_mode = display_position
        self._theme = theme
        self._pin_mode = pin_mode  # 是否启用悬浮模式
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_animation: Optional[QPropertyAnimation] = None
        self._is_pinned = False  # 当前 Toast 是否处于悬浮状态

        self._init_ui()

        # Listen for screen configuration changes (monitor plug/unplug).
        # primaryScreenChanged only fires when the PRIMARY screen changes;
        # for non-primary monitors we must also listen to screenAdded/screenRemoved.
        try:
            from PyQt6.QtGui import QGuiApplication
            QGuiApplication.primaryScreenChanged.connect(self._on_screen_config_changed)
            QGuiApplication.screenAdded.connect(self._on_screen_config_changed)
            QGuiApplication.screenRemoved.connect(self._on_screen_config_changed)
        except Exception:
            pass

    def _init_ui(self) -> None:
        """初始化 UI 组件"""
        # 无边框、不抢焦点、置顶、工具窗口
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # 外层垂直布局
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # 顶部栏：关闭按钮（左上角） + 弹簧
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(6, 4, 6, 0)
        top_bar.setSpacing(0)

        # 关闭按钮（结果 Toast 左上角显示，普通提示隐藏）
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(PIN_CLOSE_BTN_SIZE, PIN_CLOSE_BTN_SIZE)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self._close_pinned)
        self._close_btn.hide()  # 默认隐藏

        close_font = QFont()
        close_font.setFamily("Segoe UI")
        close_font.setPointSize(12)
        close_font.setWeight(QFont.Weight.Bold)
        self._close_btn.setFont(close_font)

        top_bar.addWidget(self._close_btn)
        top_bar.addStretch()

        outer_layout.addLayout(top_bar)

        # 文本标签
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumWidth(TOAST_MIN_WIDTH)

        font = QFont()
        font.setFamily("Segoe UI")
        font.setPointSize(14)
        font.setWeight(QFont.Weight.Medium)
        self._label.setFont(font)

        outer_layout.addWidget(self._label)

        # 定时器连接
        self._fade_timer.timeout.connect(self._fade_out)

        # 初始化颜色属性
        self._bg_color = self.LIGHT_BG
        self._text_color = self.LIGHT_TEXT
        self._border_color = self.LIGHT_BORDER

    def show_toast(
        self,
        text: str,
        duration_ms: int = 2000,
        is_error: bool = False,
        is_result: bool = False,
    ) -> None:
        """显示 Toast 提示

        Args:
            text: 显示文本
            duration_ms: 显示持续时间（毫秒），悬浮模式下忽略
            is_error: 是否为错误提示
            is_result: 是否为计算结果（决定是否进入悬浮模式）
        """
        # 关闭之前的悬浮 Toast（如果正在悬浮）
        if self._is_pinned:
            self._dismiss_pinned()

        # 设置文本和样式
        self._label.setText(text)

        # 判断是否进入悬浮模式：
        # 仅在 pin_mode 开启 且 is_result=True 时悬浮
        self._is_pinned = self._pin_mode and is_result and not is_error

        # 根据主题和是否错误选择颜色
        if is_error:
            self._bg_color = QColor(255, 200, 200, int(255 * TOAST_OPACITY))
            self._text_color = QColor(180, 50, 50)
            self._border_color = QColor(255, 150, 150, 150)
        elif self._theme == "dark":
            self._bg_color = self.DARK_BG_COLOR
            self._text_color = self.DARK_TEXT
            self._border_color = self.DARK_BORDER
        else:
            self._bg_color = self.LIGHT_BG
            self._text_color = self.LIGHT_TEXT
            self._border_color = self.LIGHT_BORDER

        self._label.setStyleSheet(
            f"color: {self._text_color.name()};"
            f"background: transparent;"
            f"padding: 4px;"
        )

        # Show close button for result toasts (always), hide for regular toasts
        if is_result and not is_error:
            self._close_btn.show()
            self._close_btn.setStyleSheet(
                f"color: {self._text_color.name()};"
                f"background: transparent;"
                f"border: none;"
                f"padding: 0;"
                f"margin: 0;"
            )
            # In pin mode, disable auto-dismiss timer
            if self._is_pinned:
                self._fade_timer.stop()
        else:
            self._close_btn.hide()

        # 计算尺寸
        self.adjustSize()
        min_w = max(self.width(), TOAST_MIN_WIDTH)
        min_h = max(self.height(), TOAST_MIN_HEIGHT)
        self.setFixedSize(min_w, min_h)

        # 定位
        self._position_toast()

        # 显示
        self.show()

        # 定时消失（仅非悬浮模式）
        if not self._is_pinned:
            self._fade_timer.stop()
            self._fade_timer.start(duration_ms)

        logger.debug(
            "Toast 显示: %s (%dms, pinned=%s, result=%s)",
            text[:30], duration_ms, self._is_pinned, is_result,
        )

    def _on_screen_config_changed(self) -> None:
        """显示器配置变化回调（插拔显示器）

        将当前悬浮的 Toast 重新定位到新屏幕范围内。
        解决拔掉外接显示器后悬浮窗部分落在主屏外无法关闭的问题。
        """
        if not self._is_pinned or not self.isVisible():
            return
        logger.debug("检测到屏幕配置变化，重新定位悬浮 Toast")
        # 短暂延迟后重新定位，给 Windows 时间完成窗口迁移
        QTimer.singleShot(200, self._reposition_to_safe_area)

    def _reposition_to_safe_area(self) -> None:
        """将窗口重新定位到当前屏幕的安全区域内

        优先使用鼠标所在屏幕，fallback 到主屏幕。
        确保窗口完全可见（包括关闭按钮）。
        """
        if not self._is_pinned or not self.isVisible():
            return
        self._position_toast()

    def _close_pinned(self) -> None:
        """关闭按钮回调：关闭悬浮 Toast"""
        logger.debug("悬浮 Toast 用户手动关闭")
        self._dismiss_pinned()

    def _dismiss_pinned(self) -> None:
        """立即关闭悬浮 Toast（无淡出动画）"""
        self._is_pinned = False
        self._close_btn.hide()
        self._fade_timer.stop()
        if self._fade_animation is not None:
            self._fade_animation.stop()
        self.hide()
        self.setWindowOpacity(1.0)

    def _position_toast(self) -> None:
        """根据配置定位 Toast 窗口，确保始终在屏幕可见区域内"""
        geo = self._get_screen_geometry()

        if self._position_mode == "mouse_near":
            pos = QCursor.pos()
            x = pos.x() + 15
            y = pos.y() + 15
        elif self._position_mode == "center":
            x = geo.center().x() - self.width() // 2
            y = geo.center().y() - self.height() // 2
        else:  # bottom_right
            x = geo.right() - self.width() - 30
            y = geo.bottom() - self.height() - 60

        # 安全钳制：确保窗口不超出屏幕边界（包括关闭按钮）
        x = max(geo.left() + 5, min(x, geo.right() - self.width() - 5))
        y = max(geo.top() + 5, min(y, geo.bottom() - self.height() - 5))

        self.move(x, y)

    def _get_screen_geometry(self) -> QRect:
        """获取鼠标所在屏幕的可用区域几何信息"""
        try:
            from PyQt6.QtGui import QGuiApplication
            screen = QGuiApplication.screenAt(QCursor.pos())
            if screen is not None:
                return screen.availableGeometry()
            primary = QGuiApplication.primaryScreen()
            if primary is not None:
                return primary.availableGeometry()
        except Exception:
            pass

        # 最终 fallback：使用窗口自身所在屏幕
        screen = self.screen()
        if screen is not None:
            return screen.availableGeometry()

        # 兜底
        return QRect(0, 0, 1920, 1080)

    def _fade_out(self) -> None:
        """淡出动画后隐藏窗口"""
        # 先清理之前的动画连接
        if self._fade_animation is not None:
            try:
                self._fade_animation.finished.disconnect()
            except Exception:
                pass

        self._fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self._fade_animation.setDuration(300)
        self._fade_animation.setStartValue(1.0)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.finished.connect(self._on_fade_finished)
        self._fade_animation.start()

    def _on_fade_finished(self) -> None:
        """淡出动画完成回调"""
        self.hide()
        self.setWindowOpacity(1.0)

    def paintEvent(self, event: QPaintEvent) -> None:
        """自定义绘制：阴影 + 圆角半透明背景

        手动绘制阴影层，避免 QGraphicsDropShadowEffect
        与 WA_TranslucentBackground 的兼容性问题。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 先绘制阴影（偏移的灰色圆角矩形）
        shadow_rect = self.rect().adjusted(
            TOAST_SHADOW_OFFSET,
            TOAST_SHADOW_OFFSET,
            -2 + TOAST_SHADOW_OFFSET,
            -2 + TOAST_SHADOW_OFFSET,
        )
        painter.setBrush(TOAST_SHADOW_COLOR)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(shadow_rect, TOAST_BORDER_RADIUS, TOAST_BORDER_RADIUS)

        # 再绘制主体背景（覆盖阴影的上部分）
        body_rect = self.rect().adjusted(2, 2, -2, -2)
        painter.setBrush(self._bg_color)
        painter.setPen(self._border_color)
        painter.drawRoundedRect(body_rect, TOAST_BORDER_RADIUS, TOAST_BORDER_RADIUS)

        painter.end()

    def update_theme(self, theme: str) -> None:
        """更新主题"""
        self._theme = theme

    def update_position(self, position: str) -> None:
        """更新显示位置"""
        self._position_mode = position

    def update_pin_mode(self, pin_mode: bool) -> None:
        """更新悬浮模式设置"""
        self._pin_mode = pin_mode
