"""UI Automation 文本读取模块

通过 Windows UI Automation API 直接从焦点控件读取选中文本，
完全不使用剪贴板（不发送 Ctrl+C，不清空/修改剪贴板）。

UIA 是 Windows 提供的无障碍 API，主流应用（浏览器、Office、IDE、
文本编辑器等）均支持 UIA TextPattern。
"""

import ctypes
import logging
from ctypes import wintypes
from typing import Optional

logger = logging.getLogger(__name__)

# ── COM 基础设施 ──

ole32 = ctypes.windll.ole32
oleaut32 = ctypes.windll.oleaut32

# COM 接口指针类型
IUnknownPtr = ctypes.c_void_p

# GUID 结构
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

# IID_IUIAutomation = {30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}
IID_IUIAutomation = GUID(
    0x30CBE57D, 0xD9D0, 0x452A,
    (0xAB, 0x13, 0x7A, 0xC5, 0xAC, 0x48, 0x25, 0xEE)
)
# CLSID_CUIAutomation = {FF48DBA4-60EF-4201-AA87-54103EEF594E}
CLSID_CUIAutomation = GUID(
    0xFF48DBA4, 0x60EF, 0x4201,
    (0xAA, 0x87, 0x54, 0x10, 0x3E, 0xEF, 0x59, 0x4E)
)

UIA_TextPatternId = 10014
UIA_ValuePatternId = 10002


def _com_vtable_call(this, vtable_index, restype, *argtypes):
    """调用 COM 虚函数表中的方法"""
    vtable = ctypes.cast(this, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    func = ctypes.cast(vtable[0][vtable_index], ctypes.c_void_p)
    prototype = ctypes.WINFUNCTYPE(restype, *argtypes)
    return prototype(func)


def _create_uia() -> Optional[IUnknownPtr]:
    """创建 CUIAutomation COM 对象"""
    p = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_CUIAutomation),
        None,
        1,  # CLSCTX_INPROC_SERVER
        ctypes.byref(IID_IUIAutomation),
        ctypes.byref(p),
    )
    if hr < 0:
        logger.debug("CoCreateInstance(CUIAutomation) 失败: 0x%08X", hr)
        return None
    return p.value


# ── IUIAutomation vtable ──

def _uia_get_focused_element(uia_ptr: int) -> Optional[int]:
    """IUIAutomation::GetFocusedElement → IUIAutomationElement*"""
    fn = _com_vtable_call(uia_ptr, 8, ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    elem = ctypes.c_void_p()
    hr = fn(uia_ptr, ctypes.byref(elem))
    if hr < 0 or not elem.value:
        return None
    return elem.value


# ── IUIAutomationElement vtable ──

def _element_get_current_pattern_as(elem_ptr: int, pattern_id: int) -> Optional[int]:
    """IUIAutomationElement::GetCurrentPatternAs(patternId, iid, ppv)"""
    # IID_IUIAutomationTextPattern = {32EBA289-3583-42C2-92FE-7FF86B25AA3B}
    # IID_IUIAutomationValuePattern = {A882CD42-396F-42AC-9AF9-206585704A85}
    if pattern_id == UIA_TextPatternId:
        iid = GUID(
            0x32EBA289, 0x3583, 0x42C2,
            (0x92, 0xFE, 0x7F, 0xF8, 0x6B, 0x25, 0xAA, 0x3B)
        )
    elif pattern_id == UIA_ValuePatternId:
        iid = GUID(
            0xA882CD42, 0x396F, 0x42AC,
            (0x9A, 0xF9, 0x20, 0x65, 0x85, 0x70, 0x4A, 0x85)
        )
    else:
        return None

    fn = _com_vtable_call(elem_ptr, 26,
        ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
    result = ctypes.c_void_p()
    hr = fn(elem_ptr, pattern_id, ctypes.byref(iid), ctypes.byref(result))
    if hr < 0 or not result.value:
        return None
    return result.value


def _element_get_current_value(elem_ptr: int) -> Optional[str]:
    """通过 ValuePattern 获取控件值（用于不支持 TextPattern 的简单控件）"""
    p = _element_get_current_pattern_as(elem_ptr, UIA_ValuePatternId)
    if not p:
        return None
    try:
        # IUIAutomationValuePattern::get_CurrentValue → BSTR
        fn = _com_vtable_call(p, 4,
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wintypes.BSTR))
        bstr = ctypes.c_wintypes.BSTR()
        hr = fn(p, ctypes.byref(bstr))
        if hr >= 0 and bstr.value:
            return bstr.value
    finally:
        _iunknown_release(p)
    return None


# ── IUIAutomationTextPattern vtable ──

def _text_pattern_get_selection(tp_ptr: int) -> Optional[int]:
    """IUIAutomationTextPattern::GetSelection → IUIAutomationTextRangeArray*"""
    fn = _com_vtable_call(tp_ptr, 5,
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    arr = ctypes.c_void_p()
    hr = fn(tp_ptr, ctypes.byref(arr))
    if hr < 0 or not arr.value:
        return None
    return arr.value


# ── IUIAutomationTextRangeArray vtable ──

def _text_range_array_get_length(arr_ptr: int) -> int:
    """IUIAutomationTextRangeArray::get_Length → int"""
    fn = _com_vtable_call(arr_ptr, 3,
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
    length = ctypes.c_int()
    hr = fn(arr_ptr, ctypes.byref(length))
    if hr < 0:
        return 0
    return length.value


def _text_range_array_get_element(arr_ptr: int, index: int) -> Optional[int]:
    """IUIAutomationTextRangeArray::GetElement(index) → IUIAutomationTextRange*"""
    fn = _com_vtable_call(arr_ptr, 4,
        ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    elem = ctypes.c_void_p()
    hr = fn(arr_ptr, index, ctypes.byref(elem))
    if hr < 0 or not elem.value:
        return None
    return elem.value


# ── IUIAutomationTextRange vtable ──

def _text_range_get_text(tr_ptr: int, max_len: int = -1) -> Optional[str]:
    """IUIAutomationTextRange::GetText(maxLength) → BSTR"""
    fn = _com_vtable_call(tr_ptr, 7,
        ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_wintypes.BSTR))
    bstr = ctypes.c_wintypes.BSTR()
    hr = fn(tr_ptr, max_len, ctypes.byref(bstr))
    if hr >= 0 and bstr.value:
        return bstr.value
    return None


# ── IUnknown::Release ──

def _iunknown_release(ptr: int) -> None:
    """IUnknown::Release"""
    fn = _com_vtable_call(ptr, 2, ctypes.c_ulong, ctypes.c_void_p)
    fn(ptr)


# ── 公开 API ──

def read_selected_text_via_uia() -> Optional[str]:
    """通过 Windows UI Automation 读取当前焦点控件的选中文本

    完全不使用剪贴板。

    Returns:
        选中的文本，失败时返回 None
    """
    import pythoncom
    pythoncom.CoInitialize()

    uia_ptr = _create_uia()
    if not uia_ptr:
        return None

    try:
        # 1. 获取焦点元素
        elem_ptr = _uia_get_focused_element(uia_ptr)
        if not elem_ptr:
            logger.debug("UIA: 无法获取焦点元素")
            return None

        # 2. 尝试通过 TextPattern 读取选中文本
        tp_ptr = _element_get_current_pattern_as(elem_ptr, UIA_TextPatternId)
        if tp_ptr:
            try:
                arr_ptr = _text_pattern_get_selection(tp_ptr)
                if arr_ptr:
                    try:
                        count = _text_range_array_get_length(arr_ptr)
                        result_parts = []
                        for i in range(count):
                            tr_ptr = _text_range_array_get_element(arr_ptr, i)
                            if tr_ptr:
                                try:
                                    part = _text_range_get_text(tr_ptr)
                                    if part:
                                        result_parts.append(part)
                                finally:
                                    _iunknown_release(tr_ptr)
                        if result_parts:
                            text = "".join(result_parts)
                            if text.strip():
                                logger.debug("UIA TextPattern: %s", text[:50])
                                return text
                    finally:
                        _iunknown_release(arr_ptr)
            finally:
                _iunknown_release(tp_ptr)

        # 3. TextPattern 失败，尝试 ValuePattern（适用于简单输入框）
        value = _element_get_current_value(elem_ptr)
        if value and value.strip():
            logger.debug("UIA ValuePattern: %s", value[:50])
            return value

    finally:
        _iunknown_release(uia_ptr)
        if elem_ptr:
            _iunknown_release(elem_ptr)

    return None
