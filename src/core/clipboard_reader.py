"""选中文本获取模块

负责从当前活动窗口获取选中的文本内容。
使用 Ctrl+C 兼容模式获取选中文本，操作在后台线程中执行，
避免阻塞 Qt 主线程。

使用 ctypes SendInput 直接模拟 Ctrl+C，绕过 keyboard 库的钩子处理。
INPUT 结构体使用 Windows SDK 正确的字节布局，
兼容 32 位和 64 位系统。
"""

import logging
import threading
import time
import ctypes
import ctypes.wintypes
from typing import Callable, Optional

import pyperclip

logger = logging.getLogger(__name__)

# Windows SendInput 常量
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43

user32 = ctypes.windll.user32


# --- 正确的 Windows INPUT 结构体定义 ---
# 参考：https://docs.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-input
# 关键：INPUT 包含一个 union，在 x64 上整个 INPUT 结构体大小为 40 字节

class MOUSEINPUT(ctypes.Structure):
    """Windows MOUSEINPUT 结构体"""
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    """Windows KEYBDINPUT 结构体

    dwExtraInfo 类型使用 POINTER(c_ulong) 对应 ULONG_PTR，
    在 x64 上为 8 字节指针。
    """
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    """Windows HARDWAREINPUT 结构体"""
    _fields_ = [
        ("uMsg", ctypes.wintypes.LONG),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


# INPUT 内的联合体
class _INPUT_UNION(ctypes.Union):
    """INPUT 结构体的联合体部分"""
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    """Windows INPUT 结构体（完整定义，含联合体）

    在 32 位系统上大小为 28 字节，64 位系统上为 40 字节。
    SendInput 的 cbSize 参数必须传入正确的结构体大小。
    """
    _anonymous_ = ["_"]
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_", _INPUT_UNION),
    ]


def _send_ctrl_c_via_sendinput() -> None:
    """使用 Windows SendInput API 模拟 Ctrl+C

    直接调用 SendInput，绕过 keyboard 库的钩子处理。
    模拟按键不会经过低级键盘钩子，避免与热键监听产生竞争。
    """
    extra = ctypes.c_ulong(0)
    inputs = (INPUT * 4)()

    # Ctrl 按下
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ki.wVk = VK_CONTROL
    inputs[0].ki.wScan = 0
    inputs[0].ki.dwFlags = 0
    inputs[0].ki.time = 0
    inputs[0].ki.dwExtraInfo = ctypes.pointer(extra)

    # C 按下
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].ki.wVk = VK_C
    inputs[1].ki.wScan = 0
    inputs[1].ki.dwFlags = 0
    inputs[1].ki.time = 0
    inputs[1].ki.dwExtraInfo = ctypes.pointer(extra)

    # C 释放
    inputs[2].type = INPUT_KEYBOARD
    inputs[2].ki.wVk = VK_C
    inputs[2].ki.wScan = 0
    inputs[2].ki.dwFlags = KEYEVENTF_KEYUP
    inputs[2].ki.time = 0
    inputs[2].ki.dwExtraInfo = ctypes.pointer(extra)

    # Ctrl 释放
    inputs[3].type = INPUT_KEYBOARD
    inputs[3].ki.wVk = VK_CONTROL
    inputs[3].ki.wScan = 0
    inputs[3].ki.dwFlags = KEYEVENTF_KEYUP
    inputs[3].ki.time = 0
    inputs[3].ki.dwExtraInfo = ctypes.pointer(extra)

    # 发送按键序列
    # cbSize 必须是 INPUT 结构体的大小
    cbSize = ctypes.sizeof(INPUT)
    result = user32.SendInput(4, inputs, cbSize)
    if result != 4:
        logger.warning("SendInput 发送不完整: %d/4 (cbSize=%d)", result, cbSize)


class ClipboardReader:
    """选中文本获取器

    通过 Ctrl+C 兼容模式获取当前选中的文本。
    所有耗时操作在后台线程中执行，不阻塞 Qt 主线程。
    使用 SendInput API 模拟按键，避免与 keyboard 库钩子竞争。
    """

    def __init__(self) -> None:
        self._original_clipboard: Optional[str] = None

    def get_selected_text(self, callback: Callable[[Optional[str]], None]) -> None:
        """异步获取当前活动窗口中选中的文本

        在后台线程中执行 Ctrl+C 兼容模式获取操作，
        完成后通过 callback 将结果传递回主线程。

        重要：本方法必须在 Qt 主线程上调用（FastDividerApp 通过
        QueuedConnection 信号确保这一点）。原因是剪贴板恢复任务
        需要用 QTimer.singleShot 排程，而 QTimer 的事件分发器
        只存在于 Qt 主线程上。后台线程仅做 Ctrl+C 模拟和剪贴板
        读取，不接触任何 Qt 对象，避免
        "QBasicTimer::start: current thread's event dispatcher
        has already been destroyed" 警告及由此导致的剪贴板恢复
        静默失败。

        Args:
            callback: 结果回调函数，接收 Optional[str] 参数
        """
        # 先保存剪贴板内容
        self._save_clipboard()

        # 在主线程上排程剪贴板恢复任务：
        # 后台线程总耗时大约 = 50ms(清空) + 250ms(等 Ctrl+C) + ≤24ms(3 次重试读取) ≈ 330ms
        # 留 750ms 余量，确保恢复发生在所有读取之后
        original = self._original_clipboard
        self._original_clipboard = None  # 标记已交接，避免重复恢复
        if original is not None:
            try:
                from PyQt6.QtCore import QTimer
                # 闭包捕获 original 值，避免后续按键覆盖
                QTimer.singleShot(
                    750,
                    lambda content=original: _restore_clipboard_async(content),
                )
            except Exception as e:
                logger.debug("QTimer 排程剪贴板恢复失败，将由后台线程兜底: %s", e)
                # 兜底：仍交给后台线程在结束时恢复（time.sleep + pyperclip.copy）
                self._original_clipboard = original

        thread = threading.Thread(
            target=self._get_text_in_background,
            args=(callback,),
            daemon=True,
        )
        thread.start()
        logger.debug("后台获取线程已启动")

    def _get_text_in_background(
        self,
        callback: Callable[[Optional[str]], None],
    ) -> None:
        """在后台线程中执行文本获取操作

        Args:
            callback: 结果回调函数
        """
        try:
            try:
                pyperclip.copy("")
            except Exception:
                pass

            time.sleep(0.05)

            _send_ctrl_c_via_sendinput()
            time.sleep(0.25)

            text = self._read_clipboard_with_retry(max_attempts=3)

            # 兜底恢复路径：仅当主线程排程失败回填了 _original_clipboard 时执行。
            # 正常情况下 get_selected_text 已用 QTimer.singleShot 在主线程排程恢复，
            # 此处为防御性兜底，避免警告时剪贴板永不恢复。
            fallback = self._original_clipboard
            if fallback is not None:
                self._original_clipboard = None
                time.sleep(0.5)
                try:
                    pyperclip.copy(fallback)
                    logger.debug("剪贴板内容已通过后台兜底恢复")
                except Exception as e:
                    logger.debug("后台兜底恢复剪贴板失败: %s", e)

            if text is not None and text.strip():
                logger.debug("后台获取成功: %s", text[:50])
                callback(text.strip())
            else:
                logger.warning("后台获取失败")
                callback(None)

        except Exception as e:
            logger.error("后台获取异常: %s", e)
            callback(None)

    def _read_clipboard_with_retry(self, max_attempts: int = 3) -> Optional[str]:
        """多次尝试读取剪贴板内容

        Args:
            max_attempts: 最大尝试次数

        Returns:
            获取到的文本，或 None
        """
        for attempt in range(max_attempts):
            try:
                text = pyperclip.paste()
                if text and text.strip():
                    return text
            except Exception as e:
                logger.debug("读取剪贴板失败（第%d次）: %s", attempt + 1, e)
            time.sleep(0.08)
        return None

    def _save_clipboard(self) -> None:
        """保存当前剪贴板内容"""
        try:
            self._original_clipboard = pyperclip.paste()
        except Exception:
            self._original_clipboard = None
        logger.debug("剪贴板内容已保存")


def _restore_clipboard_async(content: str) -> None:
    """异步恢复剪贴板内容的回调函数

    Args:
        content: 要恢复到剪贴板的原始内容
    """
    try:
        pyperclip.copy(content)
        logger.debug("剪贴板内容已异步恢复")
    except Exception as e:
        logger.debug("异步恢复剪贴板失败: %s", e)
