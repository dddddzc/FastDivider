"""历史记录管理模块

负责记录、查询和管理计算历史。
历史记录保存为 JSON 格式，支持查看、复制、清空和导出。

history.json schema (v2, 分组版本)：
    {
        "groups": ["groupA", "groupB"],     # 自定义组列表（"默认" 组隐式存在，不写入）
        "entries": [
            {"expression": "...", "a": 100, "b": 4, "result": 25,
             "timestamp": "...", "group": "默认"},
            ...
        ]
    }

向后兼容：若磁盘文件是旧格式（纯列表），_load 会自动迁移到 v2，
所有旧条目归入 "默认" 组，下次 _save 时写出新格式。
"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# 隐式默认组名（不可删除、不在 _groups 列表中）
DEFAULT_GROUP_NAME = "默认"


def format_timestamp(ts_str: str) -> str:
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


def _format_number(value: float, decimal_places: int) -> str:
    """按指定小数位数格式化数字"""
    return f"{value:.{decimal_places}f}"


@dataclass
class HistoryEntry:
    """一条历史记录"""
    expression: str    # 如 "100 ÷ 4 = 25"
    a: float           # 被除数
    b: float           # 除数
    result: float      # 结果
    timestamp: str     # ISO 8601 时间戳
    group: str = DEFAULT_GROUP_NAME  # 所属组别（默认 "默认"）


class HistoryManager:
    """历史记录管理器

    维护计算历史列表与自定义组别列表，自动持久化到 JSON 文件。
    默认保留最近 100 条记录（跨组累计）。
    "默认" 组始终存在、不可删除；自定义组通过 add_group/delete_group 管理。
    """

    def __init__(self, history_path: Path, max_entries: int = 100) -> None:
        self._path = history_path
        self._max = max_entries
        self._groups: list[str] = []
        self._entries: list[HistoryEntry] = []
        self._load()

    def _load(self) -> None:
        """从磁盘加载历史记录

        兼容两种格式：
        - 旧格式（纯列表）：迁移到 v2，所有条目归入 "默认" 组
        - 新格式（对象）：加载 groups + entries
        """
        if not self._path.exists():
            self._groups = []
            self._entries = []
            return

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 兼容旧格式（纯列表）
            if isinstance(data, list):
                logger.info("检测到旧格式 history.json，迁移到 v2 分组格式")
                self._groups = []
                entries_data = data
            elif isinstance(data, dict):
                self._groups = list(data.get("groups", []))
                entries_data = data.get("entries", [])
            else:
                logger.warning("history.json 格式异常，使用空数据")
                self._groups = []
                self._entries = []
                return

            entries: list[HistoryEntry] = []
            for entry in entries_data:
                try:
                    entries.append(HistoryEntry(**entry))
                except TypeError as e:
                    logger.warning("跳过损坏的历史记录条目: %s - %s", entry, e)
            self._entries = entries

            # 一致性校验：条目引用的组别若不在 _groups 中则补齐（防孤儿条目）
            referenced = {e.group for e in self._entries if e.group != DEFAULT_GROUP_NAME}
            for g in sorted(referenced):
                if g not in self._groups:
                    self._groups.append(g)
                    logger.info("补齐未注册的组别: %s", g)

            logger.info(
                "历史记录已加载: %d 条，%d 个自定义组",
                len(self._entries), len(self._groups),
            )
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("历史记录加载失败: %s", e)
            self._groups = []
            self._entries = []

    def _save(self) -> None:
        """将历史记录持久化到磁盘（v2 格式）"""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "groups": self._groups,
                        "entries": [asdict(e) for e in self._entries],
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            logger.debug(
                "历史记录已保存: %d 条，%d 个自定义组",
                len(self._entries), len(self._groups),
            )
        except IOError as e:
            logger.error("历史记录保存失败: %s", e)

    def add(
        self,
        expression: str,
        a: float,
        b: float,
        result: float,
        timestamp: str,
        group: str = DEFAULT_GROUP_NAME,
    ) -> None:
        """添加一条历史记录

        如果超过最大条数，自动删除最早的记录（跨组累计裁剪）。

        Args:
            expression: 格式化的表达式字符串
            a: 被除数
            b: 除数
            result: 计算结果
            timestamp: ISO 8601 时间戳
            group: 所属组别，默认 "默认"
        """
        # 自动注册未知组别（防御性：确保 _groups 与条目引用一致）
        if group != DEFAULT_GROUP_NAME and group not in self._groups:
            self._groups.append(group)
            logger.info("自动注册组别（由 add 触发）: %s", group)

        entry = HistoryEntry(
            expression=expression,
            a=a,
            b=b,
            result=result,
            timestamp=timestamp,
            group=group,
        )
        self._entries.append(entry)

        # 保留最近 max 条（跨组）
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]

        self._save()

    def get_all(self) -> list[HistoryEntry]:
        """获取全部历史记录"""
        return list(self._entries)

    def get_by_group(self, group: str) -> list[HistoryEntry]:
        """获取指定组别的历史记录"""
        return [e for e in self._entries if e.group == group]

    def get_by_group_with_indices(self, group: str) -> list[tuple[int, HistoryEntry]]:
        """获取指定组别的历史记录及其在全部记录中的索引"""
        return [(i, e) for i, e in enumerate(self._entries) if e.group == group]

    def clear(self) -> None:
        """清空所有历史记录（所有组）"""
        self._entries.clear()
        self._save()
        logger.info("历史记录已全部清空")

    def clear_group(self, group: str) -> None:
        """清空指定组别的历史记录（保留组本身）

        Args:
            group: 要清空的组别名
        """
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.group != group]
        removed = before - len(self._entries)
        self._save()
        logger.info("组别 %s 已清空 %d 条记录", group, removed)

    def delete_entries(self, indices: list[int]) -> None:
        """删除指定索引的历史记录

        索引是指在全部记录列表（_entries）中的位置。
        内部按降序排序后逐个删除，避免索引偏移。

        Args:
            indices: 要删除的记录索引列表
        """
        sorted_indices = sorted(set(indices), reverse=True)
        removed = 0
        for idx in sorted_indices:
            if 0 <= idx < len(self._entries):
                del self._entries[idx]
                removed += 1
        self._save()
        logger.info("已删除 %d 条记录", removed)

    def all_groups(self) -> list[str]:
        """获取全部组别（含 "默认"），"默认" 永远在首位"""
        return [DEFAULT_GROUP_NAME] + list(self._groups)

    def custom_groups(self) -> list[str]:
        """获取自定义组别列表（不含 "默认"）"""
        return list(self._groups)

    def add_group(self, name: str) -> bool:
        """新增自定义组别

        校验：非空、非 "默认"、不与已有组重名。

        Args:
            name: 组别名

        Returns:
            True 表示新增成功；False 表示校验失败
        """
        if not name or not name.strip():
            logger.warning("新增组别失败：名称为空")
            return False
        name = name.strip()
        if name == DEFAULT_GROUP_NAME:
            logger.warning("新增组别失败：名称与默认组同名")
            return False
        if name in self._groups:
            logger.warning("新增组别失败：组别已存在 - %s", name)
            return False
        self._groups.append(name)
        self._save()
        logger.info("新增组别: %s", name)
        return True

    def delete_group(self, name: str) -> bool:
        """删除自定义组别及其全部记录

        校验：不可删除 "默认"；组别必须存在。

        Args:
            name: 组别名

        Returns:
            True 表示删除成功；False 表示校验失败
        """
        if name == DEFAULT_GROUP_NAME:
            logger.warning("删除组别失败：不可删除默认组")
            return False
        if name not in self._groups:
            logger.warning("删除组别失败：组别不存在 - %s", name)
            return False
        self._groups.remove(name)
        # 同步删除该组所有记录
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.group != name]
        removed = before - len(self._entries)
        self._save()
        logger.info("删除组别: %s（连带 %d 条记录）", name, removed)
        return True

    def export_csv(
        self,
        export_path: Path,
        indices: list[int],
        decimal_places: int,
    ) -> None:
        """导出指定历史记录为 CSV 文件

        CSV 格式：无表头，每行一条记录，列为：分子,分母,结果,时间(本地格式)。

        Args:
            export_path: 导出文件路径
            indices: 要导出的记录在全部记录列表中的索引
            decimal_places: 小数位数

        Raises:
            IOError: 写入文件失败时重新抛出，由调用方处理用户提示
        """
        try:
            entries = [self._entries[i] for i in indices if 0 <= i < len(self._entries)]
            with open(export_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                for entry in entries:
                    writer.writerow([
                        _format_number(entry.a, decimal_places),
                        _format_number(entry.b, decimal_places),
                        _format_number(entry.result, decimal_places),
                        format_timestamp(entry.timestamp),
                    ])
            logger.info(
                "历史记录已导出 CSV: %s（%d 条）",
                export_path, len(entries),
            )
        except IOError as e:
            logger.error("历史记录导出失败: %s", e)
            raise
