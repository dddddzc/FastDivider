"""PyInstaller 打包脚本

将 FastDivider 打包为单文件 EXE。
使用方法：python build.py
"""

import subprocess
import sys
import shutil
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def clean_build() -> None:
    """清理本次构建（正式版）的产物和中间文件

    只清理正式版对应的文件，不影响调试版产物。
    """
    # 清理 dist 中的目标 EXE（仅正式版，不删除调试版或其他文件）
    target_exe = DIST_DIR / "FastDivider.exe"
    if target_exe.exists():
        target_exe.unlink()
        print(f"已清理: {target_exe}")

    # 清理 build 中间目录（与调试版共享）
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"已清理: {BUILD_DIR}")

    # 清理 PyInstaller 自动生成的 .spec（仅正式版）
    spec_file = PROJECT_ROOT / "FastDivider.spec"
    if spec_file.exists():
        spec_file.unlink()
        print(f"已清理: {spec_file}")

    # 清理 __pycache__ 目录
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


def get_version() -> str:
    """从 pyproject.toml 读取版本号"""
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("version"):
                version = line.split("=")[-1].strip().strip('"').strip("'")
                if version:
                    return version
    return "1.0.0"


def sync_version_info() -> None:
    """将 pyproject.toml 中的版本号同步到 version_info.txt

    确保 EXE 的 Windows 文件版本信息与实际版本一致。
    """
    version = get_version()
    parts = version.split(".")
    # Pad to 4 parts: major.minor.patch.build
    while len(parts) < 4:
        parts.append("0")
    filevers = f"({parts[0]}, {parts[1]}, {parts[2]}, {parts[3]})"
    prodvers = filevers
    version_str = f"{parts[0]}.{parts[1]}.{parts[2]}.{parts[3]}"

    version_txt = f"""# UTF-8
#
# FastDivider version info for PyInstaller
# Auto-generated from pyproject.toml by build.py

VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={prodvers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404b0',
          [
            StringStruct('CompanyName', 'FastDivider'),
            StringStruct('FileDescription', '极速除法助手 - 选中数字快速计算'),
            StringStruct('FileVersion', '{version_str}'),
            StringStruct('InternalName', 'FastDivider'),
            StringStruct('LegalCopyright', 'Copyright 2025'),
            StringStruct('OriginalFilename', 'FastDivider.exe'),
            StringStruct('ProductName', 'FastDivider'),
            StringStruct('ProductVersion', '{version_str}'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    version_file = PROJECT_ROOT / "version_info.txt"
    version_file.write_text(version_txt, encoding="utf-8")
    print(f"版本信息已同步: {version} → {version_file}")


def build_exe() -> None:
    """使用 PyInstaller 构建单文件 EXE"""
    # 同步版本信息
    sync_version_info()
    version = get_version()
    print(f"构建版本: {version}")

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

        # 版本信息
        f"--version-file={PROJECT_ROOT / 'version_info.txt'}",

        # 资源文件
        f"--add-data={PROJECT_ROOT / 'src' / 'resources' / 'icon.ico'};resources",
        f"--add-data={PROJECT_ROOT / 'src' / 'resources' / 'icon.png'};resources",
        # 嵌入 pyproject.toml 供运行时读取版本号
        f"--add-data={PROJECT_ROOT / 'pyproject.toml'};.",

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
        "--hidden-import=src.core.updater",
        "--hidden-import=src.core.uia_reader",
        "--hidden-import=src.ui",
        "--hidden-import=src.ui.toast_window",
        "--hidden-import=src.ui.tray_icon",
        "--hidden-import=src.ui.settings_dialog",
        "--hidden-import=src.ui.history_dialog",
        "--hidden-import=src.ui.update_dialog",

        # 入口脚本
        str(PROJECT_ROOT / "src" / "main.py"),
    ]

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

            # 自动创建 ZIP 包用于 GitHub Release
            zip_name = f"FastDivider-v{version}.zip"
            zip_path = DIST_DIR / zip_name
            print(f"\n正在创建 ZIP 包: {zip_name}...")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(exe_path, "FastDivider.exe")
            zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
            print(f"ZIP 包已创建: {zip_path} ({zip_size_mb:.1f} MB)")
        else:
            print("\n构建完成但未找到 EXE 文件")
    else:
        print(f"\n构建失败，退出码: {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    clean_build()
    build_exe()
