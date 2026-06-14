"""数字解析模块

负责从文本中提取唯一一个数字。支持的格式：
- 整数: 123
- 负数: -123
- 小数: 3.1415926
- 科学计数法: 1e6, 2.5E-4
- 千位分隔符: 1,234.56

提取语义（严格"唯一连续数字"）：
- 选中文本中必须仅包含一个数字 token，否则解析失败（返回 None）
- 数字 token 周围允许任意非数字字符（如空白、货币符号 $/¥/￥、括号、文字）
- 数字前紧贴的 +/- 号视为该数字的符号
- 多个数字 token 同时存在时（例如 "12 + 34" 或 "rate 3.5 of 100"）解析失败
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


_NUMBER_TOKEN_RE = re.compile(
    r"""
    [+-]?                                   # 可选正负号
    (?:
        \d{1,3}(?:,\d{3})+(?:\.\d+)?        # 千分位形式：1,234 / 1,234.56
        |
        \d+(?:\.\d+)?                       # 普通整数或小数：123 / 3.14
        |
        \.\d+                               # 纯小数无整数部分：.5
    )
    (?:[eE][+-]?\d+)?                       # 可选科学计数法
    """,
    re.VERBOSE,
)


def parse_number(text: str) -> Optional[float]:
    """从文本中解析唯一的数字

    Args:
        text: 输入文本

    Returns:
        刚好包含一个合法数字时返回 float；多个数字或无数字返回 None
    """
    if not text or not text.strip():
        return None

    candidates = [m.group() for m in _NUMBER_TOKEN_RE.finditer(text)]

    if len(candidates) != 1:
        logger.debug(
            "数字提取失败 (期望 1 个，实际 %d 个): %s",
            len(candidates), text[:80],
        )
        return None

    token = candidates[0]
    try:
        return float(token.replace(",", ""))
    except ValueError:
        logger.debug("数字 token 转换失败: %s", token)
        return None


def format_result(value: float, decimal_places: int) -> str:
    """格式化计算结果为固定小数位

    Args:
        value: 要格式化的数值
        decimal_places: 小数位数（0-9）

    Returns:
        格式化后的字符串
    """
    return f"{value:.{decimal_places}f}"


def format_division(a: float, b: float, result: float, decimal_places: int) -> str:
    """格式化除法表达式

    Args:
        a: 被除数
        b: 除数
        result: 计算结果
        decimal_places: 小数位数（0-9）

    Returns:
        格式化后的表达式字符串，如 "100 ÷ 4 = 25.00"
    """
    a_str = format_number_display(a)
    b_str = format_number_display(b)
    r_str = format_result(result, decimal_places)
    return f"{a_str} ÷ {b_str} = {r_str}"


def format_number_display(value: float) -> str:
    """格式化数字用于显示：整数显示为整数，小数去除末尾多余零"""
    if value == int(value):
        return str(int(value))
    return str(value).rstrip("0").rstrip(".")
