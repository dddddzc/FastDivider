"""选中文本获取模块

负责从当前活动窗口获取选中的文本内容。

获取方式（按优先级）：
1. UIA（Windows UI Automation）— 主方案，完全不碰剪贴板
2. Ctrl+C 剪贴板 — 兜底方案，自动保存/恢复剪贴板内容

所有耗时操作在后台线程中执行，避免阻塞 Qt 主线程。
"""

import logging
import threading
import time
import ctypes
import ctypes.wintypes
from typing import Callable, Optional

import pyperclip

from src.core.uia_reader import read_selected_text_via_uia

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

    优先使用 Windows UI Automation 直接读取选中文本（不碰剪贴板）。
    UIA 失败时回退到 Ctrl+C 剪贴板方式，并在读取后自动恢复剪贴板内容。
    """

    def __init__(self) -> None:
        self._original_clipboard: Optional[str] = None

    def get_selected_text(self, callback: Callable[[Optional[str]], None]) -> None:
        """异步获取当前活动窗口中选中的文本

        优先使用 UIA（完全不碰剪贴板）。
        UIA 在后台线程执行并返回，不阻塞主线程。
        如 UIA 未返回结果，回退到 Ctrl+C + pyperclip 方式。

        Args:
            callback: 结果回调函数，接收 Optional[str] 参数
        """
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

        1. 优先尝试 UIA（完全不碰剪贴板）
        2. UIA 失败则回退到 Ctrl+C 剪贴板方式（自动保存/恢复）
        """
        text = None

        # 方案 1：UIA（优先，不碰剪贴板）
        try:
            text = read_selected_text_via_uia()
            if text and text.strip():
                logger.debug("UIA 获取成功: %s", text[:50])
                callback(text.strip())
                return
        except Exception as e:
            logger.debug("UIA 读取失败，回退到剪贴板方式: %s", e)

        # 方案 2：Ctrl+C + 剪贴板（兜底）
        self._get_text_via_clipboard(callback)

    def _get_text_via_clipboard(
        self,
        callback: Callable[[Optional[str]], None],
    ) -> None:
        """通过 Ctrl+C 模拟 + 剪贴板获取选中文本（兜底方案）

        保存当前剪贴板 → 清空 → Ctrl+C → 读取 → 恢复剪贴板。
        整个过程在后台线程同步完成，确保剪贴板在回调前已恢复。
        """
        # 保存剪贴板
        saved = None
        try:
            saved = pyperclip.paste()
        except Exception:
            pass

        try:
            # 清空剪贴板
            try:
                pyperclip.copy("")
            except Exception:
                pass

            time.sleep(0.05)

            # 发送 Ctrl+C
            _send_ctrl_c_via_sendinput()
            time.sleep(0.25)

            # 读取剪贴板
            text = self._read_clipboard_with_retry(max_attempts=3)

        finally:
            # 始终恢复剪贴板
            try:
                if saved is not None:
                    pyperclip.copy(saved)
                    logger.debug("剪贴板已恢复")
            except Exception as e:
                logger.debug("剪贴板恢复失败: %s", e)

        if text and text.strip():
            logger.debug("剪贴板获取成功: %s", text[:50])
            callback(text.strip())
        else:
            logger.warning("剪贴板获取失败")
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
