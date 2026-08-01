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

from collaborate.errors import PremiereNotFoundError


def _require_app_path(app_path: Optional[str], hint: str) -> str:
    if not app_path:
        raise PremiereNotFoundError(f"No Premiere Pro app configured. {hint}")
    if not Path(app_path).exists():
        raise PremiereNotFoundError(f"Configured Premiere Pro app not found at {app_path}")
    return app_path


class Launcher:
    def launch(self, prproj_path: Path, app_path: Optional[str]) -> None:
        raise NotImplementedError

    def launch_blank(self, app_path: Optional[str]) -> None:
        """Launch Premiere with no project file, for creating a brand-new
        project through its own UI (there is no scriptable "create project
        with these settings" hook to drive from the outside)."""
        raise NotImplementedError

    def is_running(self) -> bool:
        raise NotImplementedError


class MacLauncher(Launcher):
    def launch(self, prproj_path: Path, app_path: Optional[str]) -> None:
        app_path = _require_app_path(app_path, "Run 'collab init' or 'collab config set premiere.app_path <path>'.")
        subprocess.run(["open", "-a", app_path, str(prproj_path)], check=True)

    def launch_blank(self, app_path: Optional[str]) -> None:
        app_path = _require_app_path(app_path, "Run 'collab init' or 'collab config set premiere.app_path <path>'.")
        subprocess.run(["open", "-a", app_path], check=True)

    def is_running(self) -> bool:
        result = subprocess.run(
            ["pgrep", "-f", "Adobe Premiere Pro"], capture_output=True, text=True
        )
        return result.returncode == 0


class WindowsLauncher(Launcher):
    """Phase 2 — not yet implemented/validated on real Windows hardware."""

    def launch(self, prproj_path: Path, app_path: Optional[str]) -> None:
        app_path = _require_app_path(app_path, "Run 'collab config set premiere.exe_path <path>'.")
        subprocess.run([app_path, str(prproj_path)], check=True)

    def launch_blank(self, app_path: Optional[str]) -> None:
        app_path = _require_app_path(app_path, "Run 'collab config set premiere.exe_path <path>'.")
        subprocess.run([app_path], check=True)

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
    raise NotImplementedError(f"Collaborate does not support launching Premiere on {system}")
