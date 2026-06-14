"""全局快捷键管理模块 - GetAsyncKeyState 轮询实现

使用 Windows GetAsyncKeyState API 通过 QTimer 轮询检测按键状态变化。
不依赖 keyboard 库或 Windows 钩子机制（WH_KEYBOARD_LL / RegisterHotKey
在 Python 3.14 x64 上钩子回调与 WM_HOTKEY 消息均不触发）。

优势：
- 在 Qt 主线程中运行，无需跨线程信号传递
- 不受 Python 版本 / 架构限制
- 50ms 轮询间隔，响应速度足够快（人类按键持续 100-200ms）
- 无 Windows 钩子竞争或消息泵问题
- 精确匹配：仅当目标组合键按下且无多余修饰键时触发，
  避免 f8 在 shift+f8 时误触发
- 纯修饰键热键支持：如 ctrl+alt 作为热键时，禁止任何非修饰键同时按下，
  避免用户做 ctrl+alt+X 操作时误触发

按键录制：
- 录制模式下扫描所有 VK 码检测按下的键
- 用户释放所有键后自动完成录制
"""

import logging
import ctypes
import ctypes.wintypes
from typing import Callable, Optional, Set

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32

# ── 虚拟键码映射 ──

VK_NAMES = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter",
    0x10: "shift", 0x11: "ctrl", 0x12: "alt",
    0x13: "pause", 0x14: "caps_lock",
    0x1B: "esc",
    0x20: "space",
    0x21: "page_up", 0x22: "page_down",
    0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2D: "insert", 0x2E: "delete",
    # F1-F12（仅保留标准键盘上实际存在的 F 键）
    # F13-F24（0x7C-0x87）已移除：这些键不存在于标准键盘上，
    # 但 GetAsyncKeyState 对部分 VK（如 0x85=f22）返回虚假的按下状态 0x8000，
    # 导致纯修饰键热键（ctrl+shift）永远无法匹配（误触发检查检测到虚假按键），
    # 同时录制时也会将虚假按键累积到结果中。
    0x70: "f1", 0x71: "f2", 0x72: "f3", 0x73: "f4",
    0x74: "f5", 0x75: "f6", 0x76: "f7", 0x77: "f8",
    0x78: "f9", 0x79: "f10", 0x7A: "f11", 0x7B: "f12",
    # 数字键
    0x30: "0", 0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4",
    0x35: "5", 0x36: "6", 0x37: "7", 0x38: "8", 0x39: "9",
    # 字母键
    0x41: "a", 0x42: "b", 0x43: "c", 0x44: "d", 0x45: "e",
    0x46: "f", 0x47: "g", 0x48: "h", 0x49: "i", 0x4A: "j",
    0x4B: "k", 0x4C: "l", 0x4D: "m", 0x4E: "n", 0x4F: "o",
    0x50: "p", 0x51: "q", 0x52: "r", 0x53: "s", 0x54: "t",
    0x55: "u", 0x56: "v", 0x57: "w", 0x58: "x", 0x59: "y",
    0x5A: "z",
    # 其他
    0x5B: "win", 0x5C: "win_right",
    0x60: "numpad_0", 0x61: "numpad_1", 0x62: "numpad_2",
    0x63: "numpad_3", 0x64: "numpad_4", 0x65: "numpad_5",
    0x66: "numpad_6", 0x67: "numpad_7", 0x68: "numpad_8",
    0x69: "numpad_9",
    0x6A: "numpad_multiply", 0x6B: "numpad_add",
    0x6C: "numpad_separator", 0x6D: "numpad_subtract",
    0x6E: "numpad_decimal", 0x6F: "numpad_divide",
    0x90: "num_lock", 0x91: "scroll_lock",
    0xBA: "semicolon", 0xBB: "equal", 0xBC: "comma",
    0xBD: "hyphen", 0xBE: "period", 0xBF: "slash",
    0xC0: "grave",
}

# 反向映射：名称 -> VK
NAME_TO_VK: dict[str, int] = {v: k for k, v in VK_NAMES.items()}

# 修饰键 VK 集合（用于精确匹配：不允许多余的修饰键，也用于"纯修饰键热键"扫描排除）
# 包含：
# - 通用修饰键（0x10-0x12）：在多数 Windows 环境下与左右键同时被 GetAsyncKeyState 置位，
#   但部分驱动 / Python 3.14 x64 组合下 0x10/0x11/0x12 不会被左右键镜像，
#   因此匹配逻辑必须把通用键和左右键视为同一"家族"，详见 _MOD_FAMILY 与 _is_modifier_family_pressed
# - 左右区分版本（0xA0-0xA5）：LSHIFT/RSHIFT/LCTRL/RCTRL/LMENU/RMENU
# - Win 键左右版本（0x5B/0x5C）
MODIFIER_VKS: set[int] = {
    0x10, 0x11, 0x12,           # SHIFT, CONTROL, MENU(Alt)
    0x5B, 0x5C,                 # LWIN, RWIN
    0xA0, 0xA1,                 # LSHIFT, RSHIFT
    0xA2, 0xA3,                 # LCONTROL, RCONTROL
    0xA4, 0xA5,                 # LMENU, RMENU
}

# 修饰键"家族"映射：每个家族代表一个逻辑修饰键，包含其所有 VK 成员。
# 匹配时只要家族中任一成员被按下即视为该修饰键被按下。
# 这样无论 Windows 上 GetAsyncKeyState 是否把通用键 0x10/0x11/0x12 与左右键镜像，
# 都能正确判定 ctrl/alt/shift 是否处于按下状态。
_MOD_FAMILY: dict[int, frozenset[int]] = {
    0x10: frozenset({0x10, 0xA0, 0xA1}),    # SHIFT family
    0x11: frozenset({0x11, 0xA2, 0xA3}),    # CONTROL family
    0x12: frozenset({0x12, 0xA4, 0xA5}),    # ALT/MENU family
    0x5B: frozenset({0x5B, 0x5C}),          # WIN family
    0x5C: frozenset({0x5B, 0x5C}),          # WIN family (alias)
    0xA0: frozenset({0x10, 0xA0, 0xA1}),    # LSHIFT alias → SHIFT family
    0xA1: frozenset({0x10, 0xA0, 0xA1}),
    0xA2: frozenset({0x11, 0xA2, 0xA3}),
    0xA3: frozenset({0x11, 0xA2, 0xA3}),
    0xA4: frozenset({0x12, 0xA4, 0xA5}),
    0xA5: frozenset({0x12, 0xA4, 0xA5}),
}

# 左右区分修饰键 VK → 对应通用键 VK 的映射，用于录制结果归一化和显示。
_SIDE_TO_GENERIC_MOD: dict[int, int] = {
    0xA0: 0x10, 0xA1: 0x10,     # LSHIFT/RSHIFT → SHIFT
    0xA2: 0x11, 0xA3: 0x11,     # LCONTROL/RCONTROL → CONTROL
    0xA4: 0x12, 0xA5: 0x12,     # LMENU/RMENU → MENU(Alt)
}

# 录制时排除的 VK（鼠标按钮等不应被录制）
EXCLUDED_RECORD_VKS: set[int] = {0x01, 0x02, 0x04, 0x05, 0x06}  # 鼠标按钮

# "纯修饰键热键"误触发检查所用的非修饰键白名单：仅扫描已知普通键，
# 避免 GetAsyncKeyState 在未定义/保留 VK 上返回意外值导致永远无法匹配。
_NON_MODIFIER_KNOWN_VKS: frozenset[int] = frozenset(
    {vk for vk in VK_NAMES if vk not in MODIFIER_VKS}
    | {vk for vk in range(0x30, 0x3A)}
    | {vk for vk in range(0x41, 0x5B)}
)


# ── 工具函数 ──

def _is_key_pressed(vk: int) -> bool:
    """检查指定虚拟键码是否当前被按下

    GetAsyncKeyState 返回 SHORT：
    - bit 15 (0x8000) = 当前物理按下状态
    """
    state = user32.GetAsyncKeyState(vk)
    return bool(state & 0x8000)


def _is_modifier_family_pressed(vk: int) -> bool:
    """检查修饰键家族中任一成员是否被按下

    某些 Windows 驱动或 Python 组合下，GetAsyncKeyState(VK_CONTROL=0x11) 不会被
    LCTRL/RCTRL 物理按键自动镜像置位，导致直接查 0x11 永远返回 False。
    通过家族集查询所有相关 VK，确保检测可靠。

    Args:
        vk: 修饰键 VK 或对应的左右版

    Returns:
        若 vk 是修饰键且其家族任一成员被按下，返回 True；
        若 vk 不是修饰键，退化为单键检查
    """
    family = _MOD_FAMILY.get(vk)
    if family is None:
        return _is_key_pressed(vk)
    for member in family:
        if _is_key_pressed(member):
            return True
    return False


def parse_hotkey_string(hotkey_str: str) -> set[int]:
    """将快捷键字符串解析为虚拟键码集合

    支持格式："f8", "shift+f8", "ctrl+alt+d", "ctrl+shift+f1"

    Args:
        hotkey_str: 快捷键字符串

    Returns:
        虚拟键码集合，如 {0x10, 0x77} 表示 shift+f8
    """
    vks: set[int] = set()
    parts = hotkey_str.lower().replace(" ", "").split("+")
    for part in parts:
        if part in NAME_TO_VK:
            vks.add(NAME_TO_VK[part])
        elif len(part) == 1 and part.isalpha():
            vks.add(ord(part.upper()))
        elif len(part) == 1 and part.isdigit():
            vks.add(0x30 + int(part))
        else:
            logger.warning("无法识别按键: %s", part)
    return vks


def vk_set_to_string(vks: set[int]) -> str:
    """将虚拟键码集合转换为快捷键字符串

    输出顺序：ctrl > alt > shift > win > 普通键（按 VK 升序）。
    例如 {alt, ctrl} → "ctrl+alt"，{shift, ctrl, f8} → "ctrl+shift+f8"。

    Args:
        vks: 虚拟键码集合

    Returns:
        快捷键字符串，如 "ctrl+shift+f8"
    """
    modifier_order = [0x11, 0x12, 0x10, 0x5B, 0x5C]  # ctrl, alt, shift, win, win_right
    mods: list[str] = []
    keys: list[str] = []

    for mod_vk in modifier_order:
        if mod_vk in vks:
            name = VK_NAMES.get(mod_vk)
            if name:
                mods.append(name)

    for vk in sorted(vks):
        if vk in MODIFIER_VKS:
            continue
        name = VK_NAMES.get(vk)
        if name:
            keys.append(name)
        elif 0x41 <= vk <= 0x5A:
            keys.append(chr(vk).lower())

    parts = mods + keys
    return "+".join(parts) if parts else ""


# ── HotkeyManager ──

class HotkeyManager(QObject):
    """全局快捷键管理器 - GetAsyncKeyState 轮询

    通过 QTimer 定时调用 GetAsyncKeyState 检测按键组合状态变化。
    所有操作在 Qt 主线程中完成，无需跨线程通信。

    释放触发逻辑：
    - 按下组合键时标记为「激活」，但不立即触发
    - 组合键从「激活」→「释放」时触发回调
    - 确保回调执行时热键的所有修饰键已释放，
      避免修饰键与 Ctrl+C 模拟按键叠加导致复制失败
    - 精确匹配：不允许多余修饰键，f8 不会在 shift+f8 时误触发
    """

    # 按键录制完成信号（可选使用，也可通过 is_recording_done() 轮询）
    recording_done = pyqtSignal(str)

    def __init__(
        self,
        on_capture: Callable[[], None],
        hotkey: str = "ctrl+shift",
    ) -> None:
        super().__init__()
        self._on_capture = on_capture
        self._main_vks: set[int] = parse_hotkey_string(hotkey)
        self._started = False

        # 轮询定时器（50ms = 20次/秒）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll_keys)

        # 状态追踪：释放触发
        self._main_active = False    # 主快捷键是否在上次检测时匹配

        # 按键录制状态
        self._recording = False
        self._recorded_vks: Optional[set[int]] = None
        self._record_released = False  # 录制中所有键是否已释放

    def start(self) -> None:
        """开始快捷键监听"""
        if self._started:
            logger.warning("快捷键已在监听中")
            return

        self._poll_timer.start()
        self._started = True
        logger.info(
            "快捷键监听已启动(轮询模式): 快捷键=%s",
            vk_set_to_string(self._main_vks),
        )

    def stop(self) -> None:
        """停止监听"""
        if not self._started:
            return

        self._poll_timer.stop()
        self._started = False
        self._main_active = False
        logger.info("快捷键监听已停止")

    def update_hotkey(self, hotkey: str) -> None:
        """动态更新快捷键绑定（无需重启定时器）"""
        self._main_vks = parse_hotkey_string(hotkey)
        self._main_active = False
        logger.info("快捷键已更新: %s", hotkey)

    # ── 轮询核心 ──

    def _poll_keys(self) -> None:
        """每 50ms 执行一次按键状态检测

        使用释放触发：组合键从「激活」→「释放」时才触发回调。
        这样确保回调执行时热键的所有键（包括修饰键）已物理释放，
        避免修饰键与 ClipboardReader 的 Ctrl+C 模拟按键叠加。
        """
        # 录制模式下只处理录制逻辑，不触发快捷键
        if self._recording:
            self._handle_recording_poll()
            return

        # 快捷键检测（释放触发）
        main_now = self._check_hotkey_match(self._main_vks)

        if not main_now and self._main_active:
            logger.info("快捷键触发(释放): %s", vk_set_to_string(self._main_vks))
            try:
                self._on_capture()
            except Exception as e:
                logger.error("快捷键回调异常: %s", e)
        self._main_active = main_now

    def _check_hotkey_match(self, target_vks: set[int]) -> bool:
        """检查快捷键组合是否精确匹配当前按键状态

        采用「家族集」语义：
        - target_vks 中的修饰键（如 0x11=ctrl）匹配整个家族 {0x11, 0xA2, 0xA3} 任一被按下
        - 普通键（如 0x77=f8）按精确 VK 检查

        要求：
        1. 目标组合中的所有键（家族集）都被按下
        2. 没有多余的修饰键家族被按下
           （避免 f8 在 shift+f8 时误触发）
        3. 若热键为纯修饰键组合（如 ctrl+alt），还需禁止任何已知非修饰键被按下，
           避免用户做 ctrl+alt+X 时误触发
        """
        target_families: set[frozenset[int]] = set()
        for vk in target_vks:
            family = _MOD_FAMILY.get(vk)
            if family is None:
                if not _is_key_pressed(vk):
                    return False
            else:
                if not any(_is_key_pressed(m) for m in family):
                    return False
                target_families.add(family)

        for generic_mod in (0x10, 0x11, 0x12, 0x5B):
            family = _MOD_FAMILY[generic_mod]
            if family in target_families:
                continue
            if any(_is_key_pressed(m) for m in family):
                return False

        if target_vks and target_vks.issubset(MODIFIER_VKS):
            for vk in _NON_MODIFIER_KNOWN_VKS:
                if _is_key_pressed(vk):
                    return False

        return True

    # ── 按键录制 ──

    def _handle_recording_poll(self) -> None:
        """录制模式下扫描所有按键

        关键：使用「曾经同时按下过」的累积并集作为录制结果，而不是「当前按下」状态。
        否则当用户先按 ctrl 再按 alt、再先释放 alt（或 ctrl）时，
        最后一帧只剩单个键被按下，会把累积的 {ctrl, alt} 覆盖成 {ctrl} 或 {alt}，
        导致组合键录制不全。

        左右区分版的修饰键（LCTRL/RCTRL/LSHIFT/RSHIFT/LMENU/RMENU）会被归一为
        对应的通用键（CONTROL/SHIFT/MENU），保证保存到配置后能被 parse_hotkey_string 正确解析。
        """
        currently_pressed: set[int] = set()
        for vk in range(256):
            if vk in EXCLUDED_RECORD_VKS:
                continue
            if not _is_key_pressed(vk):
                continue
            if vk in VK_NAMES or (0x41 <= vk <= 0x5A) or (0x30 <= vk <= 0x39):
                currently_pressed.add(vk)
            elif vk in _SIDE_TO_GENERIC_MOD:
                currently_pressed.add(_SIDE_TO_GENERIC_MOD[vk])

        if currently_pressed:
            if self._recorded_vks is None:
                self._recorded_vks = set()
            self._recorded_vks |= currently_pressed
            self._record_released = False
        elif self._recorded_vks is not None and not self._record_released:
            self._record_released = True
            self._recording = False
            result = vk_set_to_string(self._recorded_vks)
            logger.info("按键录制完成: %s", result)
            self.recording_done.emit(result)

    def start_recording(self) -> None:
        """开始按键录制

        进入录制模式，等待用户按下按键组合。
        所有键释放后自动完成录制。
        """
        self._recording = True
        self._recorded_vks = None
        self._record_released = False
        logger.debug("按键录制开始")

    def get_recorded_hotkey(self) -> Optional[str]:
        """获取录制结果

        Returns:
            录制到的快捷键字符串，如 "ctrl+alt+d"；未完成返回 None
        """
        if self._recorded_vks is None:
            return None
        return vk_set_to_string(self._recorded_vks)

    def is_recording_done(self) -> bool:
        """检查录制是否已完成"""
        return not self._recording and self._recorded_vks is not None

    def get_partial_recording(self) -> Optional[str]:
        """获取录制过程中已累积的按键组合（实时反馈用）

        与 get_recorded_hotkey 不同，本方法在录制尚未完成时也返回当前累积值，
        供 UI 实时显示"录制中: ctrl+alt"等中间反馈。
        """
        if self._recorded_vks is None or not self._recorded_vks:
            return None
        return vk_set_to_string(self._recorded_vks)

    def cancel_recording(self) -> None:
        """取消正在进行的录制（清空状态，不触发 recording_done 信号）"""
        self._recording = False
        self._recorded_vks = None
        self._record_released = False
        logger.debug("按键录制已取消")

    @staticmethod
    def validate_hotkey(hotkey: str) -> bool:
        """验证快捷键字符串是否合法"""
        vks = parse_hotkey_string(hotkey)
        return len(vks) > 0
