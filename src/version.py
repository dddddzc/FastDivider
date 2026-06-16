"""Version and identity constants for FastDivider.

All version-dependent values are centralized here.
The version number is read from pyproject.toml as the single source of truth.
"""

from pathlib import Path
from typing import Tuple

# ---------------------------------------------------------------------------
# App identity
# ---------------------------------------------------------------------------
APP_NAME = "FastDivider"
APP_DISPLAY_NAME = "FastDivider"
APP_DESCRIPTION = "极速除法助手 - 选中数字快速计算"
APP_DESCRIPTION_FULL = "极速除法助手 - 选中数字按快捷键即可计算除法，轻量级 Windows 桌面工具"
APP_COPYRIGHT = "Copyright 2025"
APP_EXE_NAME = "FastDivider.exe"
APP_MUTEX_NAME = r"Global\FastDivider_SingleInstance_Mutex"

# ---------------------------------------------------------------------------
# GitHub repository
# ---------------------------------------------------------------------------
GITHUB_OWNER = "dddddzc"
GITHUB_REPO_NAME = "FastDivider"
GITHUB_REPO = f"{GITHUB_OWNER}/{GITHUB_REPO_NAME}"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_USER_AGENT = f"FastDivider-Updater/1.0"
GITHUB_ZIP_PREFIX = "fastdivider"      # lowercase prefix for asset matching
GITHUB_ZIP_SUFFIX = ".zip"             # asset suffix for matching

# ---------------------------------------------------------------------------
# File / path names (not full paths, just the leaf names)
# ---------------------------------------------------------------------------
APP_DIR_NAME = "FastDivider"           # %APPDATA%/FastDivider
APP_LOG_NAME = "fastdivider.log"
APP_HISTORY_NAME = "FastDivider_history.txt"
APP_CONFIG_NAME = "config.json"
APP_CRASH_LOG_NAME = "crash.log"

# ---------------------------------------------------------------------------
# Windows registry
# ---------------------------------------------------------------------------
REGISTRY_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE_NAME = "FastDivider"

# ---------------------------------------------------------------------------
# Version — single source of truth: pyproject.toml
# ---------------------------------------------------------------------------
_FALLBACK_VERSION = "1.0.0"


def _read_version_from_pyproject() -> str:
    """Read the version string from pyproject.toml.

    Searches several locations so it works both in development and
    inside a PyInstaller bundle (sys._MEIPASS).
    """
    import sys

    candidates = [
        # PyInstaller bundle: pyproject.toml is embedded at the root
        Path(getattr(sys, "_MEIPASS", "")) / "pyproject.toml",
        # Development: relative to this file (src/version.py → ../../pyproject.toml)
        Path(__file__).resolve().parent.parent / "pyproject.toml",
        # Fallback: cwd
        Path("pyproject.toml"),
    ]

    for candidate in candidates:
        try:
            if candidate.exists():
                content = candidate.read_text(encoding="utf-8")
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("version"):
                        version = stripped.split("=")[-1].strip().strip('"').strip("'")
                        if version:
                            return version
        except Exception:
            continue

    return _FALLBACK_VERSION


# Module-level version (lazy; call get_version() to force re-read)
_VERSION: str = ""


def get_version() -> str:
    """Return the current app version, reading from pyproject.toml if needed."""
    global _VERSION
    if not _VERSION:
        _VERSION = _read_version_from_pyproject()
    return _VERSION


def parse_version(version_str: str) -> Tuple[int, ...]:
    """Parse a version string like 'v1.2.3' or '1.2.3' into a comparable tuple."""
    v = version_str.lstrip("v").strip()
    parts = v.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (0, 0, 0)


def get_version_tag() -> str:
    """Return the git-tag form of the version, e.g. 'v1.0.5'."""
    return f"v{get_version()}"


def get_zip_asset_name() -> str:
    """Return the release ZIP filename, e.g. 'FastDivider-v1.0.5.zip'."""
    return f"{APP_NAME}-v{get_version()}.zip"
