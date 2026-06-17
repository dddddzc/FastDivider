"""配置管理模块

负责加载、保存和管理应用程序配置。
配置文件使用 JSON 格式存储在用户数据目录中。
"""

import json
import os
import logging
from pathlib import Path
from typing import Any

from src.version import APP_DIR_NAME, APP_CONFIG_NAME

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    "hotkey": "ctrl+shift",         # 默认热键：纯修饰键组合（用户可在设置中修改）
    "display_duration": 2,          # 显示时长（秒），提示与结果统一使用
    "pin_mode": False,              # 框体长期悬浮：长期停留，可手动关闭或拖动
    "display_position": "bottom_right",  # bottom_right, center, mouse_near
    "decimal_places": 2,            # 0-9 表示固定位数
    "auto_start": False,
    "theme": "light",               # 框体颜色（light/dark），仅影响 Toast
    "history_max": 100,
}

# 配置文件路径
def _get_config_dir() -> Path:
    """获取配置文件目录路径"""
    config_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_DIR_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


class ConfigManager:
    """配置管理器

    负责配置的加载、保存和访问。
    配置变更时自动持久化到磁盘。
    """

    def __init__(self) -> None:
        self._config_dir = _get_config_dir()
        self._config_path = self._config_dir / APP_CONFIG_NAME
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """从磁盘加载配置，不存在时使用默认值

        加载后自动执行迁移：
        - 移除已废弃的键（不在 DEFAULT_CONFIG 中的键，例如旧的 reset_hotkey）
        - 修正非法的 decimal_places 值到合法范围 [0, 9]
        """
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info("配置已加载: %s", self._config_path)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("配置加载失败，使用默认值: %s", e)
                self._data = dict(DEFAULT_CONFIG)
        else:
            logger.info("配置文件不存在，使用默认值")
            self._data = dict(DEFAULT_CONFIG)
            self._save()

        # 配置迁移：清理废弃键 + 修正非法值
        self._migrate_config()

    def _migrate_config(self) -> None:
        """配置迁移：清理废弃键，修正非法值

        - 移除不在 DEFAULT_CONFIG 中的键（如旧的 reset_hotkey）
        - 将非法的 decimal_places（<0 或 >9）夹到 [0, 9] 范围
        - 变更后自动保存
        """
        changed = False

        # 移除废弃键
        obsolete_keys = [k for k in self._data if k not in DEFAULT_CONFIG]
        for k in obsolete_keys:
            del self._data[k]
            logger.info("移除废弃配置键: %s", k)
            changed = True

        # 修正非法的 decimal_places 到 [0, 9]
        dp = self._data.get("decimal_places", DEFAULT_CONFIG["decimal_places"])
        if not isinstance(dp, int) or dp < 0 or dp > 9:
            new_dp = DEFAULT_CONFIG["decimal_places"]
            logger.info("修正非法 decimal_places: %r → %d", dp, new_dp)
            self._data["decimal_places"] = new_dp
            changed = True

        if changed:
            self._save()

    def _save(self) -> None:
        """将配置持久化到磁盘"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            logger.info("配置已保存: %s", self._config_path)
        except IOError as e:
            logger.error("配置保存失败: %s", e)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self._data.get(key, default if default is not None else DEFAULT_CONFIG.get(key))

    def set(self, key: str, value: Any) -> None:
        """设置配置值并自动保存"""
        self._data[key] = value
        self._save()

    def get_all(self) -> dict[str, Any]:
        """获取全部配置"""
        return dict(self._data)

    def reset_to_defaults(self) -> None:
        """重置为默认配置"""
        self._data = dict(DEFAULT_CONFIG)
        self._save()
        logger.info("配置已重置为默认值")

    @property
    def config_dir(self) -> Path:
        """配置文件目录路径"""
        return self._config_dir

    @property
    def history_path(self) -> Path:
        """历史记录文件路径"""
        return self._config_dir / "history.json"
