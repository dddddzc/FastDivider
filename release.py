"""Release helper script.

Reads version from pyproject.toml and prints release instructions.
Usage: python release.py
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def get_version() -> str:
    """Read version from pyproject.toml"""
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


def main() -> None:
    version = get_version()
    tag = f"v{version}"

    print("=" * 60)
    print(f"  FastDivider Release Helper - v{version}")
    print("=" * 60)
    print()
    print("Release steps:")
    print()
    print("  1. Build the EXE:")
    print("     python build.py")
    print()
    print("  2. Verify the build:")
    print(f"     dist\\FastDivider.exe")
    print(f"     dist\\FastDivider-v{version}.zip")
    print()
    print("  3. Create git tag and push:")
    print(f"     git tag {tag}")
    print(f"     git push origin {tag}")
    print()
    print("  4. Create GitHub Release:")
    print(f"     Go to: https://github.com/dddddzc/FastDivider/releases/new?tag={tag}")
    print(f"     Title: {tag}")
    print(f"     Upload: dist\\FastDivider-v{version}.zip")
    print()
    print("  5. Verify auto-update:")
    print("     Users will be prompted to update on next launch.")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
