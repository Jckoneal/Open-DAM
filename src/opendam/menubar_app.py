"""macOS menu bar app — a top-bar view of the project library with
checkout/check-in/release, so the common loop needs no terminal after
first-time setup. All lock/ticket logic is the exact same code the CLI
uses (`opendam.menubar_model`, `opendam.locking`, `opendam.launcher`,
`opendam.git_ops`) — this module is only the rumps rendering + click
handling glue on top of it.

Import this module only after confirming `rumps` is installed (see
`opendam.cli.menubar`) — it's an optional extra (`pip install
open-dam[menubar]`) since rumps pulls in pyobjc, which non-macOS users and
CI shouldn't need.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import rumps
from AppKit import NSApplication

from opendam import config as config_mod
from opendam import git_ops
from opendam import locking
from opendam.errors import OpenDamError
from opendam.launcher import get_launcher
from opendam.menubar_model import REFRESH_SECONDS, AppSettings, ProjectEntry, build_entries, sync_repo

TITLE = "\U0001f3ac"  # clapperboard — a stable, recognizable glyph in a crowded menu bar


def _activate() -> None:
    """Bring this app frontmost so its next alert/window can receive
    keystrokes. rumps.App.run() does this itself once the main event loop
    starts, but our first-run setup prompt fires from __init__ — before
    run() — so without this, that dialog appears but never becomes key,
    and typing into it silently does nothing."""
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


class OpenDamMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(TITLE, quit_button="Quit")
        self.settings = AppSettings.load()
        self._busy = False
        self.refresh_timer = None
        # rumps.App.run() creates the real NSApp delegate and activates the
        # app — but only once *it* runs, which is after this constructor
        # returns. Doing first-run setup (a dialog needing keyboard focus)
        # here would show it before any of that exists. A rumps.Timer
        # registers on the calling thread's current run loop but only
        # actually fires once that run loop is spinning — i.e. after
        # App.run() has done its setup — so deferring through one gets the
        # ordering right for free, on the main thread, no extra threading.
        self._startup_timer = rumps.Timer(self._on_startup, 0.05)
        self._startup_timer.start()

    def _on_startup(self, sender) -> None:
        sender.stop()
        self._ensure_repo_configured()
        self.refresh_timer = rumps.Timer(self.on_timer, REFRESH_SECONDS)
        self.refresh_timer.start()
        self.refresh()

    # ---------- setup ----------

    def _ensure_repo_configured(self) -> None:
        if self.settings.repo_path and Path(self.settings.repo_path).is_dir():
            return
        self._prompt_for_repo_path(initial=True)

    def _prompt_for_repo_path(self, initial: bool = False) -> None:
        message = (
            "Enter the path to your Open-DAM project library "
            "(the folder you got from 'dam clone')."
        )
        window = rumps.Window(
            message=message,
            title="Open-DAM setup" if initial else "Change library folder",
            default_text=self.settings.repo_path or "",
            ok="Save",
            cancel="Quit" if initial else "Cancel",
            dimensions=(320, 24),
        )
        _activate()
        response = window.run()
        if not response.clicked:
            if initial:
                rumps.quit_application()
            return
        path = Path(response.text.strip()).expanduser()
        if not path.is_dir() or not (path / ".git").exists():
            _activate()
            rumps.alert(
                "Open-DAM",
                f"'{path}' doesn't look like a project library (no .git inside). "
                "Try again from the menu.",
            )
            if initial:
                self._prompt_for_repo_path(initial=True)
            return
        self.settings.repo_path = str(path)
        self.settings.save()

    @property
    def repo_path(self) -> Path:
        return Path(self.settings.repo_path)

    # ---------- refresh / rendering ----------

    def on_timer(self, _sender) -> None:
        if not self._busy:
            self.refresh()

    def refresh(self) -> None:
        if not self.settings.repo_path:
            return
        warning = sync_repo(self.repo_path)
        entries = build_entries(self.repo_path)
        self._render(entries, warning)

    def _render(self, entries: list[ProjectEntry], warning: Optional[str]) -> None:
        self.menu.clear()
        if warning:
            w = rumps.MenuItem(f"⚠️ {warning}")
            w.set_callback(None)
            self.menu.add(w)
            self.menu.add(rumps.separator)

        if not entries:
            empty = rumps.MenuItem("No projects in the library yet")
            empty.set_callback(None)
            self.menu.add(empty)
        for entry in entries:
            self.menu.add(self._build_item(entry))

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Refresh Now", callback=lambda _s: self.refresh()))
        self.menu.add(rumps.MenuItem("Change Library Folder…", callback=self._change_folder))

    def _change_folder(self, _sender) -> None:
        self._prompt_for_repo_path(initial=False)
        self.refresh()

    def _build_item(self, entry: ProjectEntry) -> "rumps.MenuItem":
        if entry.status == "available":
            item = rumps.MenuItem(entry.label, callback=self._make_checkout(entry))
        elif entry.status == "mine":
            item = rumps.MenuItem(entry.label)
            item.add(rumps.MenuItem("Check In", callback=self._make_checkin(entry)))
            item.add(rumps.MenuItem("Release", callback=self._make_release(entry)))
        else:  # locked by someone else — informational only
            item = rumps.MenuItem(entry.label)
            item.set_callback(None)
        return item

    # ---------- actions (run off the main thread so git/network calls never freeze the bar) ----------

    def _run_async(self, fn) -> None:
        if self._busy:
            return
        self._busy = True
        self.title = TITLE + " ⋯"  # busy indicator

        def worker():
            try:
                fn()
            except OpenDamError as e:
                rumps.alert("Open-DAM", str(e))
            except Exception as e:  # pragma: no cover - unexpected, still shouldn't crash the app
                rumps.alert("Open-DAM — unexpected error", str(e))
            finally:
                self._busy = False
                self.title = TITLE
                self.refresh()

        threading.Thread(target=worker, daemon=True).start()

    def _make_checkout(self, entry: ProjectEntry):
        def handler(_sender):
            def do():
                lock = locking.claim_lock(self.repo_path, entry.path)
                cfg = config_mod.Config.load(self.repo_path)
                app_path = cfg.premiere.app_path or cfg.premiere.exe_path
                try:
                    get_launcher().launch(entry.path, app_path)
                except OpenDamError as e:
                    rumps.alert("Open-DAM", f"Checked out {entry.name}, but couldn't launch Premiere: {e}")
                    return
                rumps.notification("Open-DAM", entry.name, f"Checked out — locked by you as of {lock.locked_at}")

            self._run_async(do)

        return handler

    def _make_checkin(self, entry: ProjectEntry):
        def handler(_sender):
            confirmed = rumps.alert(
                "Open-DAM",
                f"Have you saved and closed {entry.name} in Premiere?",
                ok="Yes",
                cancel="Not yet",
            )
            if confirmed != 1:
                return

            def do():
                identity = locking.current_identity(self.repo_path)
                dirty = git_ops.status_porcelain(self.repo_path, [str(entry.path)])
                if dirty:
                    git_ops.add(self.repo_path, [str(entry.path)])
                locking.release_lock(self.repo_path, entry.path, identity)
                git_ops.add(self.repo_path, [str(locking.lock_path_for(entry.path))])
                result = git_ops.commit(self.repo_path, f"checkin: {entry.name} by {identity['user']}")
                if not result.ok and "nothing to commit" not in result.stdout.lower():
                    raise OpenDamError(f"commit failed: {result.stderr}")
                git_ops.push_with_retry(self.repo_path)
                rumps.notification("Open-DAM", entry.name, "Checked in and released.")

            self._run_async(do)

        return handler

    def _make_release(self, entry: ProjectEntry):
        def handler(_sender):
            confirmed = rumps.alert(
                "Open-DAM",
                f"Release {entry.name} without saving a new version to the library?",
                ok="Release",
                cancel="Cancel",
            )
            if confirmed != 1:
                return

            def do():
                identity = locking.current_identity(self.repo_path)
                locking.release_lock(self.repo_path, entry.path, identity)
                git_ops.add(self.repo_path, [str(locking.lock_path_for(entry.path))])
                git_ops.commit(self.repo_path, f"release: {entry.name} by {identity['user']}")
                git_ops.push_with_retry(self.repo_path)
                rumps.notification("Open-DAM", entry.name, "Released.")

            self._run_async(do)

        return handler


def run() -> None:
    OpenDamMenuBarApp().run()
