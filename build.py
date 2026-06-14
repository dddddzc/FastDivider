"""PyInstaller 打包脚本

将 FastDivider 打包为单文件 EXE。
使用方法：python build.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def clean_build() -> None:
    """清理之前的构建产物和中间文件"""
    # 构建产物
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"已清理: {d}")

    # .spec 文件（PyInstaller 自动生成的）
    for spec in PROJECT_ROOT.glob("*.spec"):
        spec.unlink()
        print(f"已清理: {spec}")

    # __pycache__ 目录
    for pycache in PROJECT_ROOT.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
        print(f"已清理: {pycache}")


def find_pywin32_dlls() -> list[str]:
    """查找 pywin32 需要的 DLL 文件路径

    pywin32 需要 pythoncom和 pywintypes DLL，
    PyInstaller 不会自动包含它们。
    """
    dlls = []
    try:
        import pythoncom
        import pywintypes
        pythoncom_dir = Path(pythoncom.__file__).parent
        pywintypes_dir = Path(pywintypes.__file__).parent

        # 查找 DLL 文件
        for dll_name in ["pythoncom3*.dll", "pywintypes3*.dll"]:
            for search_dir in [pythoncom_dir, pywintypes_dir]:
                matches = list(search_dir.glob(dll_name))
                for match in matches:
                    dlls.append(str(match))
                    print(f"找到 pywin32 DLL: {match}")
    except ImportError:
        print("pywin32 未安装，跳过 DLL 搜索")
    except Exception as e:
        print(f"查找 pywin32 DLL 时出错: {e}")

    return dlls


def find_qt_plugins() -> list[str]:
    """查找 PyQt6 平台插件路径

    确保 qwindows.dll 等平台插件被包含。
    """
    plugins = []
    try:
        import PyQt6
        qt_dir = Path(PyQt6.__file__).parent
        platforms_dir = qt_dir / "plugins" / "platforms"
        if platforms_dir.exists():
            print(f"Qt 平台插件目录: {platforms_dir}")
            plugins.append(str(platforms_dir))
    except ImportError:
        print("PyQt6 未安装，跳过插件搜索")
    except Exception as e:
        print(f"查找 Qt 插件时出错: {e}")

    return plugins


def build_exe() -> None:
    """使用 PyInstaller 构建单文件 EXE"""
    # PyInstaller 命令参数
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=FastDivider",
        "--onefile",
        "--windowed",                    # 无控制台窗口
        "--noconfirm",
        "--clean",

        # 图标
        f"--icon={PROJECT_ROOT / 'src' / 'resources' / 'icon.ico'}",

        # 版本信息（如果文件存在）
        f"--version-file={PROJECT_ROOT / 'version_info.txt'}",

        # 资源文件
        f"--add-data={PROJECT_ROOT / 'src' / 'resources' / 'icon.ico'};resources",
        f"--add-data={PROJECT_ROOT / 'src' / 'resources' / 'icon.png'};resources",

        # 隐式导入（PyInstaller 可能遗漏的模块）
        "--hidden-import=PyQt6.sip",
        "--hidden-import=PyQt6.QtCore",
        "--hidden-import=PyQt6.QtWidgets",
        "--hidden-import=PyQt6.QtGui",
        "--hidden-import=pyperclip",
        "--hidden-import=win32api",
        "--hidden-import=win32con",
        "--hidden-import=win32gui",
        "--hidden-import=win32clipboard",
        "--hidden-import=pythoncom",
        "--hidden-import=pywintypes",
        # Qt 平台支持
        "--hidden-import=PyQt6.QtPlatformSupport",
        # src 包的所有模块
        "--hidden-import=src",
        "--hidden-import=src.app",
        "--hidden-import=src.main",
        "--hidden-import=src.core",
        "--hidden-import=src.core.config",
        "--hidden-import=src.core.number_parser",
        "--hidden-import=src.core.clipboard_reader",
        "--hidden-import=src.core.hotkey_manager",
        "--hidden-import=src.core.history",
        "--hidden-import=src.ui",
        "--hidden-import=src.ui.toast_window",
        "--hidden-import=src.ui.tray_icon",
        "--hidden-import=src.ui.settings_dialog",
        "--hidden-import=src.ui.history_dialog",

        # 入口脚本
        str(PROJECT_ROOT / "src" / "main.py"),
    ]

    # 如果没有 version_info.txt，去掉版本信息参数
    version_file = PROJECT_ROOT / "version_info.txt"
    if not version_file.exists():
        cmd = [arg for arg in cmd if not arg.startswith("--version-file")]

    # 添加 pywin32 DLL（如果找到）
    for dll in find_pywin32_dlls():
        cmd.append(f"--add-binary={dll};.")

    print("开始构建 FastDivider.exe...")
    print(f"命令: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode == 0:
        exe_path = DIST_DIR / "FastDivider.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\n构建成功！")
            print(f"EXE 路径: {exe_path}")
            print(f"文件大小: {size_mb:.1f} MB")
        else:
            print("\n构建完成但未找到 EXE 文件")
    else:
        print(f"\n构建失败，退出码: {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    clean_build()
    build_exe()
