"""Pure logic for the macOS menu bar app — no rumps/AppKit import here, so
this module (and its tests) work without the `menubar` extra installed or a
GUI session available. `menubar_app.py` is the thin rumps-specific layer that
renders what this module produces.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from collaborate import git_ops
from collaborate import locking
from collaborate import projects as projects_mod
from collaborate import tickets as tickets_mod
from collaborate.errors import OpenDamError

DEFAULT_SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "Collaborate" / "menubar.json"
REFRESH_SECONDS = 30


@dataclass
class AppSettings:
    repo_path: Optional[str] = None

    @classmethod
    def load(cls, path: Path = DEFAULT_SETTINGS_PATH) -> "AppSettings":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(repo_path=data.get("repo_path"))

    def save(self, path: Path = DEFAULT_SETTINGS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")


@dataclass
class ProjectEntry:
    name: str
    path: Path
    status: str  # "available" | "mine" | "locked"
    locked_by: Optional[str]
    open_tickets: int

    @property
    def label(self) -> str:
        glyph = {"available": "○", "mine": "●", "locked": "\U0001f512"}[self.status]
        text = f"{glyph} {self.name}"
        if self.status == "locked":
            text += f" — {self.locked_by}"
        if self.open_tickets:
            text += f" ({self.open_tickets})"
        return text


def sync_repo(repo_path: Path) -> Optional[str]:
    """Fetch + fast-forward pull, tolerating failure like `collab list` does.
    Returns a warning string on failure, None on success."""
    try:
        git_ops.fetch(repo_path)
        git_ops.pull_ff_only(repo_path)
        return None
    except OpenDamError as e:
        return f"Could not sync with remote — showing local state ({e})"


def build_entries(repo_path: Path) -> list[ProjectEntry]:
    me = locking.current_identity(repo_path)["user"]
    entries = []
    for p in projects_mod.discover(repo_path):
        open_count = len(tickets_mod.open_tickets(p.path))
        if p.lock and p.lock.is_locked():
            if p.lock.is_held_by(me):
                entries.append(ProjectEntry(p.name, p.path, "mine", None, open_count))
            else:
                entries.append(
                    ProjectEntry(p.name, p.path, "locked", p.lock.locked_by.get("user", "?"), open_count)
                )
        else:
            entries.append(ProjectEntry(p.name, p.path, "available", None, open_count))
    return entries
