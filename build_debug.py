"""调试版 PyInstaller 打包脚本

保留控制台窗口，方便查看运行时错误信息。
使用方法：python build_debug.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def clean_build() -> None:
    """清理本次构建（调试版）的产物和中间文件

    只清理调试版对应的文件，不影响正式版产物。
    """
    # 清理 dist 中的目标 EXE（仅调试版，不删除正式版或其他文件）
    target_exe = DIST_DIR / "FastDivider_debug.exe"
    if target_exe.exists():
        target_exe.unlink()
        print(f"已清理: {target_exe}")

    # 清理 build 中间目录（与正式版共享）
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"已清理: {BUILD_DIR}")

    # 清理 PyInstaller 自动生成的 .spec（仅调试版）
    spec_file = PROJECT_ROOT / "FastDivider_debug.spec"
    if spec_file.exists():
        spec_file.unlink()
        print(f"已清理: {spec_file}")

    # 清理 __pycache__ 目录
    for pycache in PROJECT_ROOT.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
        print(f"已清理: {pycache}")


def build_debug_exe() -> None:
    """构建调试版 EXE（保留控制台窗口）"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=FastDivider_debug",
        "--onefile",
        # 注意：不加 --windowed，保留控制台窗口！
        "--noconfirm",
        "--clean",

        # 图标
        f"--icon={PROJECT_ROOT / 'src' / 'resources' / 'icon.ico'}",

        # 资源文件
        f"--add-data={PROJECT_ROOT / 'src' / 'resources' / 'icon.ico'};resources",
        f"--add-data={PROJECT_ROOT / 'src' / 'resources' / 'icon.png'};resources",

        # 隐式导入
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
        "--hidden-import=PyQt6.QtPlatformSupport",
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

    # 添加 pywin32 DLL（如果找到）
    try:
        import pythoncom
        import pywintypes
        for mod in [pythoncom, pywintypes]:
            dll_dir = Path(mod.__file__).parent
            for dll_name in ["pythoncom3*.dll", "pywintypes3*.dll"]:
                matches = list(dll_dir.glob(dll_name))
                for match in matches:
                    cmd.append(f"--add-binary={match};.")
                    print(f"找到 DLL: {match}")
    except ImportError:
        print("pywin32 未安装")

    print("\n=== 构建调试版 FastDivider_debug.exe ===")
    print("(保留控制台窗口，可看到所有错误输出)\n")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode == 0:
        exe_path = DIST_DIR / "FastDivider_debug.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\n调试版构建成功！")
            print(f"EXE 路径: {exe_path}")
            print(f"文件大小: {size_mb:.1f} MB")
            print(f"\n运行 {exe_path} 即可看到控制台窗口中的所有输出和错误信息")
        else:
            print("\n构建完成但未找到 EXE 文件")
    else:
        print(f"\n构建失败，退出码: {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    clean_build()
    build_debug_exe()
