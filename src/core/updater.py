"""更新检测模块

通过 GitHub Releases API 检查新版本，下载 ZIP 包并解压替换当前 EXE，
实现自动更新功能。

更新流程：
1. 检查 GitHub Releases 获取最新版本号
2. 与当前版本比较
3. 如有新版本，下载 ZIP 包到临时目录
4. 从 ZIP 中提取 EXE
5. 生成替换脚本（.bat），在旧进程退出后替换并重启
"""

import json
import logging
import os
import ssl
import sys
import tempfile
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QThread, pyqtSlot

logger = logging.getLogger(__name__)

# GitHub 仓库信息
GITHUB_REPO = "dddddzc/FastDivider"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# 请求去抖：最小检查间隔（秒）
MIN_CHECK_INTERVAL = 30

# 重试参数
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # 秒，指数退避：2, 4, 8


def get_current_version() -> str:
    """获取当前运行的版本号

    优先从 pyproject.toml 读取，fallback 到硬编码版本。
    """
    # 尝试从 pyproject.toml 读取（开发环境）
    try:
        if hasattr(sys, '_MEIPASS'):
            # 打包后的环境，从内部文件读取
            pyproject_path = Path(sys._MEIPASS) / "pyproject.toml"
        else:
            pyproject_path = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"

        if pyproject_path.exists():
            content = pyproject_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("version"):
                    # 解析 'version = "1.0.0"' 格式
                    version = line.split("=")[-1].strip().strip('"').strip("'")
                    if version:
                        return version
    except Exception:
        pass

    # Fallback 硬编码版本
    return "1.0.0"


def parse_version(version_str: str) -> tuple:
    """将版本号字符串解析为可比较的元组

    "v1.0.0" → (1, 0, 0)
    "1.0.0"  → (1, 0, 0)
    """
    v = version_str.lstrip("v").strip()
    parts = v.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        logger.warning("无法解析版本号: %s", version_str)
        return (0, 0, 0)


def _is_retryable_error(error: Exception) -> bool:
    """判断是否为可重试的网络错误"""
    if isinstance(error, urllib.error.HTTPError):
        # 403 rate limit 不应重试
        # 5xx 服务端错误可以重试
        return 500 <= error.code < 600
    # SSL EOF、IncompleteRead、timeout 均可重试
    return True


def _http_get(url: str, timeout: int = 15) -> bytes:
    """带重试的 HTTP GET 请求

    对网络抖动（SSL EOF、IncompleteRead 等）自动重试，最多 3 次。
    指数退避：2s → 4s → 8s

    Args:
        url: 请求 URL
        timeout: 超时秒数

    Returns:
        响应体 bytes

    Raises:
        urllib.error.URLError: 重试耗尽后仍失败
    """
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "FastDivider-Updater/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()

        except urllib.error.HTTPError as e:
            if e.code == 403:
                # 频率限制不重试
                raise
            if not (500 <= e.code < 600):
                raise
            last_error = e
        except (urllib.error.URLError, ssl.SSLError, OSError) as e:
            last_error = e

        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("HTTP 请求失败 (第%d次重试, %ds后重试): %s",
                           attempt + 1, delay, last_error)
            time.sleep(delay)

    raise last_error


class UpdateCheckThread(QThread):
    """后台线程：检查 GitHub 最新版本

    使用 QThread 避免阻塞 UI。
    """

    # 信号：检查完成
    # result: (has_update: bool, latest_version: str, current_version: str, error: str|None)
    finished = pyqtSignal(bool, str, str, object)

    def run(self) -> None:
        """在后台线程中执行版本检查"""
        try:
            latest_version, download_url, body = self._check_github()
            current = get_current_version()

            logger.info("当前版本: %s, 最新版本: %s", current, latest_version)

            has_update = parse_version(latest_version) > parse_version(current)
            self.finished.emit(has_update, latest_version, current, None)

        except urllib.error.HTTPError as e:
            if e.code == 403:
                msg = "GitHub API 频率限制，请稍后再试"
            elif e.code == 404:
                msg = "尚未发布任何版本"
            else:
                msg = f"服务器错误 (HTTP {e.code})"
            logger.error("版本检查失败: %s", msg)
            current = get_current_version()
            self.finished.emit(False, current, current, msg)
        except Exception as e:
            logger.error("版本检查失败: %s", e)
            current = get_current_version()
            # 给用户友好的中文提示
            if "EOF" in str(e) or "IncompleteRead" in str(e):
                msg = "网络连接不稳定，请稍后重试"
            elif "timeout" in str(e).lower():
                msg = "连接超时，请检查网络"
            elif "getaddrinfo" in str(e).lower():
                msg = "无法解析 GitHub 域名，请检查网络"
            else:
                msg = f"检查更新失败: {e}"
            self.finished.emit(False, current, current, msg)

    def _check_github(self) -> tuple[str, str, str]:
        """访问 GitHub API 获取最新 release 信息

        Returns:
            (version, download_url, body)

        Raises:
            Exception: 网络错误或 API 错误
        """
        raw = _http_get(GITHUB_API_URL, timeout=15)
        data = json.loads(raw.decode("utf-8"))

        tag_name = data.get("tag_name", "v0.0.0")
        body = data.get("body", "")
        assets = data.get("assets", [])

        # 规范化版本号：去掉 'v' 前缀
        version = tag_name.lstrip("v")

        # 查找 FastDivider zip 包（文件名匹配 FastDivider*.zip）
        download_url = ""
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.startswith("fastdivider") and name.endswith(".zip"):
                download_url = asset.get("browser_download_url", "")
                break

        if not download_url:
            raise Exception("未在 release 中找到 FastDivider ZIP 包")

        return version, download_url, body


class UpdateDownloadThread(QThread):
    """后台线程：下载新版本 ZIP 并解压提取 EXE

    使用 QThread 避免阻塞 UI，支持进度报告。
    """

    progress = pyqtSignal(int)     # 下载进度百分比 (0-100)
    finished = pyqtSignal(bool, str)  # (success, file_path_or_error)

    def __init__(self, download_url: str) -> None:
        super().__init__()
        self._download_url = download_url

    def run(self) -> None:
        """在后台线程中下载文件"""
        try:
            tmp_path = self._download()
            self.finished.emit(True, tmp_path)
        except Exception as e:
            logger.error("下载失败: %s", e)
            msg = f"下载失败: {e}"
            if "EOF" in str(e) or "IncompleteRead" in str(e):
                msg = "下载中断（网络不稳定），请稍后重试"
            elif "timeout" in str(e).lower():
                msg = "下载超时，请检查网络"
            self.finished.emit(False, msg)

    def _download(self) -> str:
        """下载 ZIP 到临时目录，解压提取 EXE，返回 EXE 临时路径"""
        tmp_dir = tempfile.gettempdir()
        zip_path = os.path.join(tmp_dir, "FastDivider_update.zip")
        exe_path = os.path.join(tmp_dir, "FastDivider_update.exe")

        raw = _http_get(self._download_url, timeout=300)
        total_size = len(raw)

        with open(zip_path, "wb") as f:
            f.write(raw)

        logger.info("下载完成: %s (%d bytes)", zip_path, total_size)

        # 从 ZIP 中提取 FastDivider.exe
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                logger.info("ZIP 内容: %s", names)
                # 查找 FastDivider.exe（可能在子目录中）
                exe_name = None
                for name in names:
                    if name.lower().endswith("fastdivider.exe"):
                        exe_name = name
                        break

                if not exe_name:
                    raise Exception("ZIP 中未找到 FastDivider.exe")

                # 提取到临时目录
                zf.extract(exe_name, tmp_dir)
                extracted = os.path.join(tmp_dir, exe_name)

                # 如果解压路径与目标路径不同，重命名
                if extracted != exe_path:
                    if os.path.exists(exe_path):
                        os.remove(exe_path)
                    os.rename(extracted, exe_path)
        finally:
            # 清理 ZIP 文件
            try:
                os.remove(zip_path)
            except Exception:
                pass

        logger.info("解压完成: %s", exe_path)
        return exe_path


class Updater(QObject):
    """更新管理器

    协调版本检查、下载、替换重启的完整流程。

    用法：
        updater = Updater()
        updater.check_for_updates()  # 启动后台检查
    """

    update_available = pyqtSignal(str, str)  # (current_version, latest_version)
    no_update = pyqtSignal()
    error_occurred = pyqtSignal(str)         # error message
    download_progress = pyqtSignal(int)       # 0-100
    download_complete = pyqtSignal()
    update_ready = pyqtSignal(str)            # temp file path

    def __init__(self) -> None:
        super().__init__()
        self._check_thread: Optional[UpdateCheckThread] = None
        self._download_thread: Optional[UpdateDownloadThread] = None
        self._latest_download_url: str = ""
        self._latest_version: str = ""
        self._temp_exe_path: str = ""
        self._last_check_time: float = 0.0

    def get_current_exe_path(self) -> str:
        """获取当前 EXE 的完整路径"""
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller 打包后，sys.executable 就是 EXE 路径
            return sys.executable
        else:
            # 开发环境，返回 Python 解释器路径（仅用于测试）
            return sys.executable

    def check_for_updates(self) -> bool:
        """启动后台版本检查

        内置去抖：如果距离上次检查不足 MIN_CHECK_INTERVAL 秒，则跳过。

        Returns:
            True 如果已启动检查，False 如果因去抖而跳过
        """
        now = time.time()
        if now - self._last_check_time < MIN_CHECK_INTERVAL:
            logger.info("距上次检查不足 %ds，跳过（去抖）", MIN_CHECK_INTERVAL)
            return False
        self._last_check_time = now

        self._check_thread = UpdateCheckThread()
        self._check_thread.finished.connect(self._on_check_finished)
        self._check_thread.start()
        return True

    @pyqtSlot(bool, str, str, object)
    def _on_check_finished(
        self,
        has_update: bool,
        latest_version: str,
        current_version: str,
        error: Optional[str],
    ) -> None:
        """版本检查完成回调"""
        if error:
            self.error_occurred.emit(error)
            return

        if has_update:
            self._latest_version = latest_version
            # 从检查线程获取下载 URL
            self.update_available.emit(current_version, latest_version)
        else:
            self.no_update.emit()

    def start_download(self) -> None:
        """开始下载新版本

        必须先调用 check_for_updates 且 update_available 已触发。
        """
        # 通过 API 获取下载 URL
        self._start_download_internal()

    def _start_download_internal(self) -> None:
        """内部：通过 API 获取下载 URL 并开始下载"""
        try:
            raw = _http_get(GITHUB_API_URL, timeout=15)
            data = json.loads(raw.decode("utf-8"))

            assets = data.get("assets", [])
            download_url = ""
            for asset in assets:
                name = asset.get("name", "").lower()
                if name.startswith("fastdivider") and name.endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    break

            if not download_url:
                self.error_occurred.emit("未在 release 中找到 FastDivider ZIP 包")
                return

            self._latest_download_url = download_url

        except Exception as e:
            self.error_occurred.emit(f"获取下载链接失败: {e}")
            return

        self._download_thread = UpdateDownloadThread(self._latest_download_url)
        self._download_thread.progress.connect(self.download_progress.emit)
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.start()

    @pyqtSlot(bool, str)
    def _on_download_finished(self, success: bool, result: str) -> None:
        """下载完成回调"""
        if success:
            self._temp_exe_path = result
            self.download_complete.emit()
            self.update_ready.emit(result)
        else:
            self.error_occurred.emit(result)

    def apply_update_and_restart(self) -> None:
        """应用更新：生成替换脚本并退出当前进程

        替换脚本流程：
        1. 等待当前进程退出（最多 30 秒）
        2. 用新 EXE 覆盖旧 EXE
        3. 启动新 EXE
        4. 删除临时文件和脚本自身
        """
        old_exe = self.get_current_exe_path()
        new_exe = self._temp_exe_path

        if not new_exe or not os.path.exists(new_exe):
            logger.error("临时更新文件不存在: %s", new_exe)
            return

        # 检查是否在打包环境中
        if not hasattr(sys, '_MEIPASS'):
            logger.warning("开发环境不支持自动替换，跳过更新")
            return

        # 生成替换批处理脚本
        bat_path = os.path.join(tempfile.gettempdir(), "FastDivider_update.bat")
        bat_content = f'''@echo off
chcp 65001 >nul
echo FastDivider 正在更新...

:wait_exit
timeout /t 1 /nobreak >nul
tasklist /FI "IMAGENAME eq FastDivider.exe" 2>NUL | find /I "FastDivider.exe" >NUL
if "%ERRORLEVEL%"=="0" goto wait_exit

echo 正在替换文件...
copy /Y "{new_exe}" "{old_exe}"
if %ERRORLEVEL% neq 0 (
    echo 替换失败！请手动替换。
    echo 新版本文件位于: {new_exe}
    pause
    exit /b 1
)

echo 更新完成，正在启动...
start "" "{old_exe}"

del "{new_exe}" 2>nul
del "%~f0" 2>nul
'''

        try:
            with open(bat_path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(bat_content)
            logger.info("替换脚本已生成: %s", bat_path)
        except Exception as e:
            logger.error("生成替换脚本失败: %s", e)
            return

        # 启动替换脚本（使用 CREATE_NEW_PROCESS_GROUP 让批处理独立运行）
        import subprocess
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
            logger.info("替换脚本已启动，退出当前进程")
        except Exception as e:
            logger.error("启动替换脚本失败: %s", e)
            return

        # 退出当前应用
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
