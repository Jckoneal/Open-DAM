"""Pure logic for the macOS menu bar app — no rumps/AppKit import here, so
this module (and its tests) work without the `menubar` extra installed or a
GUI session available. `menubar_app.py` is the thin rumps-specific layer that
renders what this module produces.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from collaborate import git_ops
from collaborate import locking
from collaborate import projects as projects_mod
from collaborate import tickets as tickets_mod
from collaborate.config import DEFAULT_STALE_LOCK_HOURS
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


def elapsed_label(iso_timestamp: Optional[str]) -> str:
    """Compact "Xh Ym" (or "Xm" under an hour, "Xh" on the hour) elapsed
    since an ISO-8601 UTC timestamp in the format locking.utcnow_iso()
    produces. Empty string if there's no timestamp to measure from."""
    if not iso_timestamp:
        return ""
    then = datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    total_minutes = max(0, int((datetime.now(timezone.utc) - then).total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours == 0 and minutes == 0:
        return ""  # fresh enough that a "0m" suffix would just be noise
    if hours == 0:
        return f"{minutes}m"
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h {minutes}m"


def is_stale(iso_timestamp: Optional[str], stale_lock_hours: int = DEFAULT_STALE_LOCK_HOURS) -> bool:
    if not iso_timestamp:
        return False
    then = datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() >= stale_lock_hours * 3600


@dataclass
class ProjectEntry:
    name: str
    path: Path
    status: str  # "available" | "mine" | "locked"
    locked_by: Optional[str]
    locked_at: Optional[str]
    open_tickets: int
    stale: bool = False

    @property
    def label(self) -> str:
        glyph = {"available": "○", "mine": "●", "locked": "\U0001f512"}[self.status]
        text = f"{glyph} {self.name}"
        elapsed = elapsed_label(self.locked_at)
        if self.status == "mine":
            if elapsed:
                text += f" — {elapsed}"
        elif self.status == "locked":
            text += f" — {self.locked_by}"
            if elapsed:
                text += f" · {elapsed}"
        if self.stale:
            text += " ⚠"
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


def check_media_root(media_root: Optional[str]) -> Optional[str]:
    """Mirrors `collab doctor`'s media_root check. A warning string if
    configured but not found on this machine, None otherwise — including
    when unconfigured, which is a valid, unwarned state just like the CLI."""
    if media_root and not Path(media_root).exists():
        return f"Media root missing — {media_root} not mounted"
    return None


def build_entries(repo_path: Path, stale_lock_hours: int = DEFAULT_STALE_LOCK_HOURS) -> list[ProjectEntry]:
    me = locking.current_identity(repo_path)["user"]
    entries = []
    for p in projects_mod.discover(repo_path):
        open_count = len(tickets_mod.open_tickets(p.path))
        if p.lock and p.lock.is_locked():
            locked_at = p.lock.locked_at
            stale = is_stale(locked_at, stale_lock_hours)
            if p.lock.is_held_by(me):
                entries.append(ProjectEntry(p.name, p.path, "mine", None, locked_at, open_count, stale))
            else:
                entries.append(
                    ProjectEntry(
                        p.name, p.path, "locked", p.lock.locked_by.get("user", "?"),
                        locked_at, open_count, stale,
                    )
                )
        else:
            entries.append(ProjectEntry(p.name, p.path, "available", None, None, open_count, False))
    return entries


def group_entries(entries: list[ProjectEntry]) -> "tuple[list[ProjectEntry], list[ProjectEntry]]":
    """Split into (mine, others) — mine surfaces prominently at the top of
    the menu as a focus card; others keep their natural discovery order
    below it, available and locked-by-others interleaved."""
    mine = [e for e in entries if e.status == "mine"]
    others = [e for e in entries if e.status != "mine"]
    return mine, others


def freed_by_others(old_entries: list[ProjectEntry], new_entries: list[ProjectEntry]) -> list[str]:
    """Project names locked by someone else in `old_entries` that are now
    available in `new_entries` — freed since the last refresh by someone
    else's check-in, not by an action we ourselves just took (those already
    get their own confirmation from the action that caused them)."""
    was_locked_by_other = {e.name for e in old_entries if e.status == "locked"}
    now_available = {e.name for e in new_entries if e.status == "available"}
    return sorted(was_locked_by_other & now_available)


@dataclass
class PaletteAction:
    """One runnable action on a project, as offered by the search/command
    palette (wireframe option 1c, "search-first · keyboard command
    palette") — verbs first, not rows."""
    verb: str  # "Check out" | "Check in" | "Add note"
    project: str
    entry: ProjectEntry

    @property
    def label(self) -> str:
        return f"{self.verb} — {self.project}"


def palette_actions(entries: list[ProjectEntry]) -> list[PaletteAction]:
    """One or two actionable verbs per project, in palette order: your own
    checkouts get "Check in" (the most likely next action) plus "Add note";
    available projects get "Check out"; locked-by-others get "Add note" —
    the only thing you can do to a project you don't hold, same as clicking
    it in the menu does."""
    actions = []
    for e in entries:
        if e.status == "mine":
            actions.append(PaletteAction("Check in", e.name, e))
            actions.append(PaletteAction("Add note", e.name, e))
        elif e.status == "available":
            actions.append(PaletteAction("Check out", e.name, e))
        else:  # locked by someone else
            actions.append(PaletteAction("Add note", e.name, e))
    return actions


def filter_actions(actions: list[PaletteAction], query: str) -> list[PaletteAction]:
    """Case-insensitive substring match on the project name (not the verb —
    typing "ep0" should find every action on Ep01, not just ones whose verb
    happens to contain those letters), preserving palette_actions' relative
    order. An empty/blank query returns everything unfiltered."""
    q = query.strip().lower()
    if not q:
        return list(actions)
    return [a for a in actions if q in a.project.lower()]
