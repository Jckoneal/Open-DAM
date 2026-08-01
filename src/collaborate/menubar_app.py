"""macOS menu bar app — a top-bar view of the project library with
checkout/check-in/release, so the common loop needs no terminal after
first-time setup. All lock/ticket logic is the exact same code the CLI
uses (`collaborate.menubar_model`, `collaborate.locking`, `collaborate.launcher`,
`collaborate.git_ops`) — this module is only the rumps rendering + click
handling glue on top of it.

Layout follows the "focus card" direction from the Curate Menubar
Wireframes design (claude.ai/design project f07f3abc-ac37-405a-9a13-
7839e2b826b4): whatever you currently hold surfaces as its own section at
the top of the menu, with inline Check In/Release; everything else — free
to check out or locked by someone — follows below under a plain "Projects"
header. Per that design's own annotation ("the bar glyph stays a pure
template image; amber only appears inside the popover"), the status-bar
icon itself never changes color or shape for any state — only the menu
contents and the transient title-text suffix do.

Import this module only after confirming `rumps` is installed (see
`collaborate.cli.menubar`) — it's an optional extra (`pip install
collaborate[menubar]`) since rumps pulls in pyobjc, which non-macOS users and
CI shouldn't need.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Optional

import rumps
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagDeviceIndependentFlagsMask,
    NSEventModifierFlagShift,
)
from PyObjCTools import AppHelper

from collaborate import config as config_mod
from collaborate import git_ops
from collaborate import locking
from collaborate import tickets as tickets_mod
from collaborate.errors import OpenDamError
from collaborate.launcher import get_launcher
from collaborate.menubar_model import (
    REFRESH_SECONDS,
    AppSettings,
    PaletteAction,
    ProjectEntry,
    build_entries,
    check_media_root,
    elapsed_label,
    freed_by_others,
    group_entries,
    palette_actions,
    sync_repo,
)
from collaborate.menubar_palette import SearchPalette

# A real macOS template image (see assets/ — sourced from the design project
# above), not an emoji: template images get free light/dark-menu-bar and
# click-highlight adaptation from AppKit that a plain title glyph doesn't.
ICON_PATH = str(Path(__file__).parent / "assets" / "menubar-icon@2x.png")

# Virtual keycode for 'C' on a US keyboard layout — global hotkeys
# conventionally key off physical key position (keyCode), not the typed
# character, since that stays stable regardless of modifier state.
HOTKEY_KEYCODE = 8
HOTKEY_MODIFIERS = NSEventModifierFlagCommand | NSEventModifierFlagShift


def _activate() -> None:
    """Bring this app frontmost so its next alert/window can actually
    receive keystrokes.

    We're a bare Python process run via the `collab` console script, not a
    real .app bundle — so unlike a bundled app (which gets its activation
    policy from Info.plist's LSUIElement key), this process has no
    reliable default activation policy. Without explicitly setting one,
    activateIgnoringOtherApps_ can be a no-op: the dialog paints on top
    visually, its field even shows a focus ring, but the OS keeps routing
    actual keystrokes to whatever app (e.g. the Terminal we were launched
    from) was frontmost. Accessory = no Dock icon (right for a
    menu-bar-only app) but still lets us properly become the active app.
    """
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app.activateIgnoringOtherApps_(True)


class OpenDamMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Collaborate", icon=ICON_PATH, template=True, quit_button=None)
        self.settings = AppSettings.load()
        self._busy = False
        self._last_entries: Optional[list] = None
        self.refresh_timer = None
        self._palette = SearchPalette(on_run=self._run_palette_action)
        self._hotkey_monitor = None
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
        self._register_global_hotkey()
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
            "Enter the path to your Collaborate project library "
            "(the folder you got from 'collab clone')."
        )
        window = rumps.Window(
            message=message,
            title="Collaborate setup" if initial else "Change library folder",
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
                "Collaborate",
                f"'{path}' doesn't look like a project library (no .git inside). "
                "Try again from the menu.",
            )
            if initial:
                self._prompt_for_repo_path(initial=True)
            return
        self.settings.repo_path = str(path)
        self.settings.save()

    @property
    def repo_path(self) -> Optional[Path]:
        # Must never raise: rumps' internal callback dispatch
        # (call_as_function_or_method) does inspect.getmembers(app,
        # predicate=inspect.ismethod) before invoking ANY callback, which
        # evaluates every property via getattr — including this one. A
        # raising property here breaks every menu click and timer tick
        # app-wide, not just code paths that actually read repo_path.
        if not self.settings.repo_path:
            return None
        return Path(self.settings.repo_path)

    # ---------- refresh / rendering ----------

    def on_timer(self, _sender) -> None:
        if not self._busy:
            self.refresh()

    def refresh(self) -> None:
        if not self.settings.repo_path:
            return
        warning = sync_repo(self.repo_path)
        cfg = config_mod.Config.load(self.repo_path)
        media_warning = check_media_root(cfg.media_root)
        entries = build_entries(self.repo_path, cfg.stale_lock_hours)

        freed = freed_by_others(self._last_entries, entries) if self._last_entries is not None else []
        self._last_entries = entries

        self._render(entries, [w for w in (warning, media_warning) if w])
        if freed:
            self._flash_title(f"✓ {', '.join(freed)} free")

    def _render(self, entries: list[ProjectEntry], warnings: list[str]) -> None:
        self.menu.clear()
        for w in warnings:
            item = rumps.MenuItem(f"⚠️ {w}")
            item.set_callback(None)
            self.menu.add(item)
        if warnings:
            self.menu.add(rumps.separator)

        self.menu.add(rumps.MenuItem("Search…", callback=self._open_search_palette, key="f"))
        self.menu.add(rumps.separator)

        mine, others = group_entries(entries)

        if mine:
            header = rumps.MenuItem("CHECKED OUT BY YOU" if len(mine) > 1 else "CHECKED OUT BY YOU")
            header.set_callback(None)
            self.menu.add(header)
            for entry in mine:
                self.menu.add(self._build_item(entry))
            self.menu.add(rumps.separator)

        section = rumps.MenuItem("Projects")
        section.set_callback(None)
        self.menu.add(section)
        if not others and not mine:
            empty = rumps.MenuItem("No projects in the library yet")
            empty.set_callback(None)
            self.menu.add(empty)
        for entry in others:
            self.menu.add(self._build_item(entry))

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("New Project…", callback=self._make_new_project(), key="n"))
        self.menu.add(rumps.MenuItem("Sync Now", callback=lambda _s: self.refresh(), key="r"))
        self.menu.add(rumps.MenuItem("Settings…", callback=self._change_folder, key=","))
        self.menu.add(rumps.MenuItem("Quit Collaborate", callback=rumps.quit_application, key="q"))

    def _change_folder(self, _sender) -> None:
        self._prompt_for_repo_path(initial=False)
        self.refresh()

    def _build_item(self, entry: ProjectEntry) -> "rumps.MenuItem":
        if entry.status == "available":
            item = rumps.MenuItem(entry.label, callback=self._make_checkout(entry))
        elif entry.status == "mine":
            item = rumps.MenuItem(entry.label)
            item.add(rumps.MenuItem("Check In…", callback=self._make_checkin(entry)))
            item.add(rumps.MenuItem("Release", callback=self._make_release(entry)))
        else:  # locked by someone else — click offers to leave a note
            item = rumps.MenuItem(entry.label, callback=self._make_locked_info(entry))
        return item

    # ---------- actions (git/network work off the main thread so it can't freeze the bar) ----------

    def _run_async(self, fn) -> None:
        """Run fn() on a background thread — but fn() must be pure git/lock
        work and return a presenter tuple describing what to show
        afterward, never touch rumps/AppKit itself. AppKit enforces
        main-thread-only UI access (confirmed by real crashes: "NSWindow
        should only be instantiated on the main thread", layout-engine
        corruption warnings) — building menu items, alerts, and
        notifications all have to happen back on the main thread, which is
        what AppHelper.callAfter marshals this to."""
        if self._busy:
            return
        self._busy = True
        self.title = " ⋯"  # busy indicator, appended after the icon

        def worker():
            present = None
            try:
                present = fn()
            except OpenDamError as e:
                present = ("alert", "Collaborate", str(e))
            except Exception as e:  # pragma: no cover - unexpected, still shouldn't crash the app
                present = ("alert", "Collaborate — unexpected error", str(e))
            AppHelper.callAfter(self._async_finished, present)

        threading.Thread(target=worker, daemon=True).start()

    def _async_finished(self, present) -> None:
        """Runs on the main thread via AppHelper.callAfter."""
        self._busy = False
        self.title = ""
        if present:
            kind, *args = present
            try:
                if kind == "alert":
                    _activate()
                    rumps.alert(*args)
                else:
                    # rumps.notification needs a real .app bundle identity
                    # (a CFBundleIdentifier from an actual Info.plist) to
                    # register with the OS notification center — which a
                    # bare script run via the `collab` console script will
                    # never have. Rather than depend on something
                    # structurally unavailable to us, show success in the
                    # menu bar title itself, which always works.
                    _, subtitle, message = args
                    self._flash_title(f"✓ {subtitle}")
            except Exception as e:
                # Still best-effort beyond that: the underlying git/lock
                # operation already succeeded or failed for real by this
                # point; refresh() below must run regardless, or the menu
                # silently stops reflecting reality (looks like "checkout
                # didn't happen" when it actually did).
                print(f"Collaborate: could not show {kind}: {e}")
        self.refresh()

    def _flash_title(self, text: str, seconds: float = 2.5) -> None:
        self.title = f" {text}"
        rumps.Timer(self._end_flash, seconds).start()

    def _end_flash(self, timer) -> None:
        timer.stop()
        self.title = ""

    def _prompt_text(self, title: str, message: str, ok: str = "OK") -> Optional[str]:
        """A single-line text prompt. Returns the trimmed text, or None if
        cancelled or left blank."""
        _activate()
        window = rumps.Window(message=message, title=title, ok=ok, cancel="Cancel", dimensions=(300, 24))
        response = window.run()
        if not response.clicked:
            return None
        text = response.text.strip()
        return text or None

    def _make_checkout(self, entry: ProjectEntry):
        def handler(_sender):
            def do():
                lock = locking.claim_lock(self.repo_path, entry.path)
                cfg = config_mod.Config.load(self.repo_path)
                app_path = cfg.premiere.app_path or cfg.premiere.exe_path
                try:
                    get_launcher().launch(entry.path, app_path)
                except OpenDamError as e:
                    return ("alert", "Collaborate", f"Checked out {entry.name}, but couldn't launch Premiere: {e}")
                return ("notify", "Collaborate", entry.name, f"Checked out — locked by you as of {lock.locked_at}")

            self._run_async(do)

        return handler

    def _make_checkin(self, entry: ProjectEntry):
        def handler(_sender):
            _activate()
            confirmed = rumps.alert(
                "Collaborate",
                f"Have you saved and closed {entry.name} in Premiere?",
                ok="Yes",
                cancel="Not yet",
            )
            if confirmed != 1:
                return

            _activate()
            window = rumps.Window(
                message="Describe what changed (optional):",
                title=f"Check In — {entry.name}",
                ok="Push",
                cancel="Cancel",
                dimensions=(320, 60),
            )
            window.add_button("Push & Keep Lock")
            response = window.run()
            if response.clicked == 0:
                return
            keep_lock = response.clicked == 2
            message = response.text.strip()

            def do():
                identity = locking.current_identity(self.repo_path)
                dirty = git_ops.status_porcelain(self.repo_path, [str(entry.path)])
                if dirty:
                    git_ops.add(self.repo_path, [str(entry.path)])
                if not keep_lock:
                    locking.release_lock(self.repo_path, entry.path, identity)
                    git_ops.add(self.repo_path, [str(locking.lock_path_for(entry.path))])
                commit_msg = message or f"checkin: {entry.name} by {identity['user']}"
                result = git_ops.commit(self.repo_path, commit_msg)
                if not result.ok and "nothing to commit" not in result.stdout.lower():
                    raise OpenDamError(f"commit failed: {result.stderr}")
                git_ops.push_with_retry(self.repo_path)
                status = "Checked in — lock kept." if keep_lock else "Checked in and released."
                return ("notify", "Collaborate", entry.name, status)

            self._run_async(do)

        return handler

    def _make_release(self, entry: ProjectEntry):
        def handler(_sender):
            _activate()
            confirmed = rumps.alert(
                "Collaborate",
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
                return ("notify", "Collaborate", entry.name, "Released.")

            self._run_async(do)

        return handler

    def _make_locked_info(self, entry: ProjectEntry):
        """Locked-by-someone-else projects are still clickable: nothing on
        your machine changes, but you can leave a note for whoever holds
        it — matching the wireframe's "Nothing on your machine was
        changed. You can leave a note instead." alert."""
        def handler(_sender):
            _activate()
            elapsed = elapsed_label(entry.locked_at)
            since = f" {elapsed} ago" if elapsed else ""
            confirmed = rumps.alert(
                "Collaborate",
                f"{entry.name} is locked by {entry.locked_by}{since}. Nothing on your "
                "machine was changed. You can leave a note instead.",
                ok="Add Note…",
                cancel="OK",
            )
            if confirmed != 1:
                return
            self._prompt_and_add_note(entry)

        return handler

    def _prompt_and_add_note(self, entry: ProjectEntry) -> None:
        """Shared by the locked-project menu click (which confirms via an
        alert first) and the search palette's "Add note" action (whose
        intent is already explicit from having searched and selected it,
        so it skips straight here)."""
        text = self._prompt_text("Add Note", f"Note for {entry.name}:", ok="Add")
        if not text:
            return

        def do():
            identity = locking.current_identity(self.repo_path)
            ticket = tickets_mod.create(entry.path, text, identity)
            git_ops.add(self.repo_path, [str(tickets_mod.ticket_path(entry.path, ticket.id))])
            result = git_ops.commit(
                self.repo_path, f"ticket: add {ticket.id} to {entry.name} by {identity['user']}"
            )
            if not result.ok and "nothing to commit" not in result.stdout.lower():
                raise OpenDamError(f"commit failed: {result.stderr}")
            git_ops.push_with_retry(self.repo_path)
            return ("notify", "Collaborate", entry.name, "Note added.")

        self._run_async(do)

    # ---------- search / command palette ----------

    def _open_search_palette(self, _sender=None) -> None:
        if not self.repo_path:
            return
        _activate()
        # Reuse the last refresh's snapshot for instant opening rather than
        # doing a fresh sync — the palette is meant to be instantaneous;
        # whichever action gets run does its own fresh git work regardless.
        entries = self._last_entries
        if entries is None:
            entries = build_entries(self.repo_path, config_mod.Config.load(self.repo_path).stale_lock_hours)
        self._palette.show(palette_actions(entries))

    def _run_palette_action(self, action: PaletteAction) -> None:
        if action.verb == "Check out":
            self._make_checkout(action.entry)(None)
        elif action.verb == "Check in":
            self._make_checkin(action.entry)(None)
        elif action.verb == "Add note":
            self._prompt_and_add_note(action.entry)

    @staticmethod
    def _is_hotkey_event(event) -> bool:
        """Matching logic pulled out of the NSEvent monitor's closure so it
        can be exercised directly in a test against a plain fake object
        (anything with .keyCode()/.modifierFlags()) — real NSEvents aren't
        something a test can synthesize."""
        flags = event.modifierFlags() & NSEventModifierFlagDeviceIndependentFlagsMask
        return event.keyCode() == HOTKEY_KEYCODE and flags == HOTKEY_MODIFIERS

    def _register_global_hotkey(self) -> None:
        """Best-effort: ⌘⇧C opens the palette from anywhere, matching the
        wireframe. NSEvent's *global* monitor needs Accessibility/Input
        Monitoring permission granted (System Settings -> Privacy &
        Security) to the process actually running this — for a bare
        script under a shared interpreter (not a signed .app), that grant
        is tied to that interpreter's path and can be awkward to keep
        across reinstalls. Registration itself never fails without the
        permission; the handler just silently never fires — the "Search…"
        menu item (key="f") always works regardless, as a guaranteed
        fallback."""
        def handler(event):
            if self._is_hotkey_event(event):
                self._open_search_palette()

        self._hotkey_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, handler
        )

    def _make_new_project(self):
        def handler(_sender):
            name = self._prompt_text("New Project", "Name for the new project:", ok="Create")
            if not name:
                return

            def do():
                cfg = config_mod.Config.load(self.repo_path)
                if not (cfg.template_path and Path(cfg.template_path).exists()):
                    # No template configured: the CLI's manual-save flow
                    # needs an interactive terminal to wait for you to save
                    # in Premiere and confirm — there's no clean way to do
                    # that multi-step wait from a menu click, so point at
                    # the Terminal flow instead of half-implementing it.
                    return (
                        "alert", "Collaborate",
                        "No template is configured, so creating a project this way needs "
                        f"the Terminal: run 'collab new {name}' there — it walks you through "
                        "saving a new project by hand. (Set a template with 'collab config "
                        "set template_path <path>' to create projects from here instead.)",
                    )
                target = name if name.endswith(".prproj") else f"{name}.prproj"
                target_path = self.repo_path / target
                if target_path.exists():
                    return ("alert", "Collaborate", f"'{target}' already exists in the library.")

                git_ops.fetch(self.repo_path)
                git_ops.pull_ff_only(self.repo_path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(cfg.template_path, target_path)

                identity = locking.current_identity(self.repo_path)
                git_ops.add(self.repo_path, [str(target_path)])
                result = git_ops.commit(self.repo_path, f"new project: {target} by {identity['user']}")
                if not result.ok and "nothing to commit" not in result.stdout.lower():
                    raise OpenDamError(f"commit failed: {result.stderr}")
                git_ops.push_with_retry(self.repo_path)

                lock = locking.claim_lock(self.repo_path, target_path)
                app_path = cfg.premiere.app_path or cfg.premiere.exe_path
                try:
                    get_launcher().launch(target_path, app_path)
                except OpenDamError as e:
                    return ("alert", "Collaborate", f"Created {name}, but couldn't launch Premiere: {e}")
                return (
                    "notify", "Collaborate", name,
                    f"Created and checked out — locked by you as of {lock.locked_at}",
                )

            self._run_async(do)

        return handler


def run() -> None:
    OpenDamMenuBarApp().run()
