#!/usr/bin/env python3
"""Build a standalone FBD Lab .exe and create a GitHub release.

Usage:
    python build_release.py [--no-release]

Steps:
  1. Read version from pyproject.toml
  2. Build standalone .exe with PyInstaller
  3. Tag the commit and push
  4. Create a GitHub release with the .exe attached

Requires: pyinstaller, gh (GitHub CLI, authenticated)
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PYPROJECT = ROOT / "pyproject.toml"
DIST_DIR = ROOT / "dist"


def get_version() -> str:
    text = PYPROJECT.read_text()
    m = re.search(r'version\s*=\s*"(.+?)"', text)
    if not m:
        print("Error: could not read version from pyproject.toml")
        sys.exit(1)
    return m.group(1)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"> {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"Command failed with exit code {result.returncode}")
        sys.exit(1)
    return result


def build_exe(version: str) -> Path:
    sep = ";" if sys.platform == "win32" else ":"
    build_name = "FBD_Lab"
    release_name = f"FBD Lab v{version}"
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", build_name,
        "--icon", str(ROOT / "fbd_lab" / "ui" / "icon.png"),
        "--add-data", f"{ROOT / 'fbd_lab' / 'ui'}{sep}ui",
        "--add-data", f"{ROOT / 'fbd_lab' / 'fonts'}{sep}fonts",
        "--add-data", f"{ROOT / 'fbd_lab' / 'models' / 'FBD1.png'}{sep}models",
        "--add-data", f"{ROOT / 'pyproject.toml'}{sep}.",
        str(ROOT / "fbd_lab" / "main.py"),
    ])

    built_path = DIST_DIR / f"{build_name}.exe"
    if not built_path.exists():
        print(f"Error: expected {built_path} not found after build")
        sys.exit(1)

    exe_path = DIST_DIR / f"{release_name}.exe"
    shutil.move(built_path, exe_path)

    print(f"Built: {exe_path} ({exe_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return exe_path


def create_release(version: str, exe_path: Path):
    tag = f"v{version}"

    # Check if tag already exists
    result = subprocess.run(["git", "tag", "-l", tag], capture_output=True, text=True)
    if tag in result.stdout.strip().splitlines():
        print(f"Error: tag {tag} already exists. Bump the version in pyproject.toml first.")
        sys.exit(1)

    run(["git", "tag", tag])
    run(["git", "push", "origin", "--tags"])
    run([
        "gh", "release", "create", tag,
        str(exe_path),
        "--title", f"FBD Lab {tag}",
        "--generate-notes",
    ])
    print(f"Release {tag} created.")


def check_git_clean():
    """Abort if there are uncommitted changes or the branch is behind the remote."""
    # Check for uncommitted changes (staged or unstaged)
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if result.stdout.strip():
        print("Error: you have uncommitted changes. Commit or stash them before releasing.")
        print(result.stdout)
        sys.exit(1)

    # Fetch latest remote state
    subprocess.run(["git", "fetch", "origin", "main"], capture_output=True)

    # Check if local is behind remote
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD..origin/main"],
        capture_output=True, text=True,
    )
    behind = int(result.stdout.strip() or "0")
    if behind > 0:
        print(f"Error: local branch is {behind} commit(s) behind origin/main. Pull first.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Build and release FBD Lab")
    parser.add_argument("--no-release", action="store_true", help="Only build, skip GitHub release")
    parser.add_argument("-f", "--force", action="store_true", help="Skip git clean/behind checks")
    args = parser.parse_args()

    version = get_version()
    print(f"Version: {version}")

    if not args.no_release:
        if not args.force:
            check_git_clean()
        # Push before building to ensure the release matches pushed code
        print("Pushing to origin...")
        run(["git", "push", "origin", "main"])

    exe_path = build_exe(version)

    if not args.no_release:
        create_release(version, exe_path)
    else:
        print("Skipping release (--no-release).")


if __name__ == "__main__":
    main()
