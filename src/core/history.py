"""历史记录管理模块

负责记录、查询和管理计算历史。
历史记录保存为 JSON 格式，支持查看、复制、清空和导出。
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    """一条历史记录"""
    expression: str  # 如 "100 ÷ 4 = 25"
    a: float         # 被除数
    b: float         # 除数
    result: float    # 结果
    timestamp: str   # ISO 8601 时间戳


class HistoryManager:
    """历史记录管理器

    维护计算历史列表，自动持久化到 JSON 文件。
    默认保留最近 100 条记录。
    """

    def __init__(self, history_path: Path, max_entries: int = 100) -> None:
        self._path = history_path
        self._max = max_entries
        self._entries: list[HistoryEntry] = []
        self._load()

    def _load(self) -> None:
        """从磁盘加载历史记录"""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._entries = [
                    HistoryEntry(**entry) for entry in data
                ]
                logger.info("历史记录已加载: %d 条", len(self._entries))
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("历史记录加载失败: %s", e)
                self._entries = []

    def _save(self) -> None:
        """将历史记录持久化到磁盘"""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(
                    [asdict(e) for e in self._entries],
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            logger.debug("历史记录已保存: %d 条", len(self._entries))
        except IOError as e:
            logger.error("历史记录保存失败: %s", e)

    def add(self, expression: str, a: float, b: float, result: float, timestamp: str) -> None:
        """添加一条历史记录

        如果超过最大条数，自动删除最早的记录。

        Args:
            expression: 格式化的表达式字符串
            a: 被除数
            b: 除数
            result: 计算结果
            timestamp: ISO 8601 时间戳
        """
        entry = HistoryEntry(
            expression=expression,
            a=a,
            b=b,
            result=result,
            timestamp=timestamp,
        )
        self._entries.append(entry)

        # 保留最近 max 条
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]

        self._save()

    def get_all(self) -> list[HistoryEntry]:
        """获取全部历史记录"""
        return list(self._entries)

    def clear(self) -> None:
        """清空所有历史记录"""
        self._entries.clear()
        self._save()
        logger.info("历史记录已清空")

    def export_txt(self, export_path: Path) -> None:
        """导出历史记录为 TXT 文件

        Args:
            export_path: 导出文件路径
        """
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                for entry in self._entries:
                    f.write(f"{entry.expression}\n")
            logger.info("历史记录已导出: %s", export_path)
        except IOError as e:
            logger.error("历史记录导出失败: %s", e)
            raise
