"""OS-specific Premiere Pro launching.

Deliberately does not try to detect "user finished editing" via process-exit
polling — Premiere has no reliable scriptable close hook without
ExtendScript/UXP, and the process staying alive doesn't mean this particular
project is still open. `is_running()` is only ever used as a soft hint in the
checkin confirmation prompt, never to gate/block anything.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional

from opendam.errors import PremiereNotFoundError


class Launcher:
    def launch(self, prproj_path: Path, app_path: Optional[str]) -> None:
        raise NotImplementedError

    def is_running(self) -> bool:
        raise NotImplementedError


class MacLauncher(Launcher):
    def launch(self, prproj_path: Path, app_path: Optional[str]) -> None:
        if not app_path:
            raise PremiereNotFoundError(
                "No Premiere Pro app configured. Run 'dam init' or 'dam config set premiere.app_path <path>'."
            )
        if not Path(app_path).exists():
            raise PremiereNotFoundError(f"Configured Premiere Pro app not found at {app_path}")
        subprocess.run(["open", "-a", app_path, str(prproj_path)], check=True)

    def is_running(self) -> bool:
        result = subprocess.run(
            ["pgrep", "-f", "Adobe Premiere Pro"], capture_output=True, text=True
        )
        return result.returncode == 0


class WindowsLauncher(Launcher):
    """Phase 2 — not yet implemented/validated on real Windows hardware."""

    def launch(self, prproj_path: Path, app_path: Optional[str]) -> None:
        if not app_path:
            raise PremiereNotFoundError(
                "No Premiere Pro executable configured. Run 'dam config set premiere.exe_path <path>'."
            )
        if not Path(app_path).exists():
            raise PremiereNotFoundError(f"Configured Premiere Pro executable not found at {app_path}")
        subprocess.run([app_path, str(prproj_path)], check=True)

    def is_running(self) -> bool:
        result = subprocess.run(
            ["tasklist"], capture_output=True, text=True
        )
        return "Adobe Premiere Pro.exe" in result.stdout


def get_launcher() -> Launcher:
    system = platform.system()
    if system == "Darwin":
        return MacLauncher()
    if system == "Windows":
        return WindowsLauncher()
    raise NotImplementedError(f"Open-DAM does not support launching Premiere on {system}")
