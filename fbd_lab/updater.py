"""Auto-update check for FBD Lab.

On startup (exe builds only), queries the GitHub releases API in a background
thread. If a newer version is found, prompts the user to download and replace
the running exe, then restarts.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication

GITHUB_API_URL = "https://api.github.com/repos/cenmir/FBD_Lab/releases/latest"
REQUEST_TIMEOUT = 5  # seconds — don't stall startup


def _parse_version(tag: str) -> tuple[int, ...]:
    """'v0.8.3' -> (0, 8, 3)"""
    return tuple(int(x) for x in tag.lstrip("v").split("."))


# ---------------------------------------------------------------------------
# Background version check
# ---------------------------------------------------------------------------

class VersionCheckThread(QThread):
    """Fetch the latest release info without blocking the UI."""

    result = pyqtSignal(str, str, str)  # (latest_version, download_url, release_url)
    failed = pyqtSignal()               # network error or no release found

    def run(self):
        try:
            req = Request(GITHUB_API_URL, headers={"Accept": "application/json"})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            tag = data.get("tag_name", "")
            release_url = data.get("html_url", "")
            assets = data.get("assets", [])
            exe_url = ""
            for a in assets:
                if a["name"].lower().endswith(".exe"):
                    exe_url = a["browser_download_url"]
                    break
            if tag and exe_url:
                self.result.emit(tag, exe_url, release_url)
            else:
                self.failed.emit()
        except (URLError, OSError, json.JSONDecodeError, KeyError):
            self.failed.emit()


# ---------------------------------------------------------------------------
# Download with progress
# ---------------------------------------------------------------------------

def _download_with_progress(url: str, dest: Path, parent=None) -> bool:
    """Download a file showing a progress dialog. Returns True on success."""
    try:
        req = Request(url)
        resp = urlopen(req, timeout=30)
        total = int(resp.headers.get("Content-Length", 0))

        progress = QProgressDialog("Downloading update...", "Cancel", 0, total or 1, parent)
        progress.setWindowTitle("FBD Lab Update")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        with open(dest, "wb") as f:
            downloaded = 0
            while True:
                QApplication.processEvents()
                if progress.wasCanceled():
                    progress.close()
                    return False
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    progress.setValue(downloaded)

        progress.close()
        return True
    except (URLError, OSError):
        return False


# ---------------------------------------------------------------------------
# Update logic
# ---------------------------------------------------------------------------

def _replace_and_restart(new_exe: Path):
    """Replace the running exe with the downloaded one and restart.

    On Windows a running exe can't be overwritten or renamed by itself.
    We write a small batch script that waits for this process to exit,
    then does the swap and launches the new version.
    """
    import subprocess

    current = Path(sys.executable)
    backup = current.with_suffix(".old")
    bat = current.with_suffix(".update.bat")

    # Write a batch script that:
    # 1. Waits for the current process to exit (taskkill already happened via sys.exit)
    # 2. Retries the rename in a loop until the file is unlocked
    # 3. Swaps old -> .old, new -> current name
    # 4. Launches the new exe
    # 5. Deletes itself
    # Use the directory + filenames explicitly to avoid path issues
    exe_dir = current.parent
    cur_name = current.name
    bak_name = backup.name
    new_name = new_exe.name

    bat.write_text(
        f'@echo off\n'
        f'cd /d "{exe_dir}"\n'
        f':wait\n'
        f'timeout /t 1 /nobreak >nul\n'
        f'del "{bak_name}" 2>nul\n'
        f'ren "{cur_name}" "{bak_name}" 2>nul\n'
        f'if errorlevel 1 goto wait\n'
        f'ren "{new_name}" "{cur_name}"\n'
        f'start "" "{cur_name}"\n'
        f'del "%~f0"\n',
        encoding="utf-8",
    )

    # Launch the batch script detached and exit
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    )
    sys.exit(0)


def prompt_update(parent, current_version: str, latest_tag: str,
                  exe_url: str, release_url: str):
    """Show update dialog and handle the download/replace flow."""
    current = _parse_version(current_version)
    latest = _parse_version(latest_tag)

    if latest <= current:
        return  # up to date

    msg = QMessageBox(parent)
    msg.setWindowTitle("Update Available")
    msg.setText(
        f"A new version of FBD Lab is available!\n\n"
        f"Current: v{current_version}\n"
        f"Latest:  {latest_tag}\n\n"
        f"Download and install the update?"
    )
    msg.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    msg.setDefaultButton(QMessageBox.StandardButton.Yes)

    if msg.exec() != QMessageBox.StandardButton.Yes:
        return

    # Download to a temp file next to the exe
    current_exe = Path(sys.executable)
    tmp_path = current_exe.parent / f"FBD_Lab_update_{latest_tag}.exe"

    if not _download_with_progress(exe_url, tmp_path, parent):
        QMessageBox.warning(parent, "Update Failed",
                            "Download failed or was cancelled.")
        if tmp_path.exists():
            tmp_path.unlink()
        return

    # Replace and restart
    try:
        _replace_and_restart(tmp_path)
    except Exception as e:
        QMessageBox.warning(parent, "Update Failed",
                            f"Could not replace the exe:\n{e}\n\n"
                            f"The update was downloaded to:\n{tmp_path}")


# ---------------------------------------------------------------------------
# Public API — call from main.py after window.show()
# ---------------------------------------------------------------------------

def check_for_updates(parent, current_version: str):
    """Start a background version check. If newer, prompt the user."""
    if not getattr(sys, "frozen", False):
        return  # only check in exe builds

    # Clean up leftover .old from a previous update
    backup = Path(sys.executable).with_suffix(".old")
    if backup.exists():
        try:
            backup.unlink()
        except OSError:
            pass

    thread = VersionCheckThread()

    def on_result(latest_tag, exe_url, release_url):
        prompt_update(parent, current_version, latest_tag, exe_url, release_url)

    thread.result.connect(on_result)
    # Keep a reference so the thread isn't garbage-collected
    parent._update_thread = thread
    thread.start()
