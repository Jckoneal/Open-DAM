"""Tests for the rumps-specific app layer. Skipped entirely when the
optional `menubar` extra (rumps/pyobjc) isn't installed — menubar_model.py
carries all the logic that can (and must) be tested without it; this file
covers only the thin rumps glue on top."""

import inspect

import pytest

rumps = pytest.importorskip("rumps")

from typer.testing import CliRunner

from collaborate import config as config_mod
from collaborate import locking
from collaborate import menubar_app
from collaborate import tickets as tickets_mod
from collaborate.cli import app as cli_app
from collaborate.menubar_model import AppSettings, build_entries, sync_repo

runner = CliRunner()


class _FakeSuccessfulLauncher:
    def launch(self, *_a, **_kw):
        pass


class _FakeWindow:
    """Stands in for rumps.Window — its .run() would need a live GUI
    session and keyboard input, neither available in a test process."""
    def __init__(self, clicked, text=""):
        self.clicked = clicked
        self.text = text

    def add_button(self, _name):
        pass

    def run(self):
        return self


def test_repo_path_never_raises_when_unconfigured():
    """Regression: rumps' internal dispatch (call_as_function_or_method)
    runs inspect.getmembers(app, predicate=inspect.ismethod) before invoking
    ANY callback — menu clicks, timer ticks, all of it — and that evaluates
    every property via getattr, including repo_path. A raising property
    here previously broke every callback app-wide while the library folder
    wasn't yet configured, not just code paths that read repo_path."""
    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=None)

    assert app.repo_path is None
    # the exact call rumps makes internally before invoking any callback
    inspect.getmembers(app, predicate=inspect.ismethod)


def test_repo_path_returns_path_when_configured(tmp_path):
    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(tmp_path))

    assert app.repo_path == tmp_path
    inspect.getmembers(app, predicate=inspect.ismethod)


def test_checkout_do_never_calls_rumps_directly(alice, monkeypatch):
    """Regression: do() closures used to call rumps.alert/rumps.notification
    directly from inside the background thread _run_async spawns them on —
    real crashes followed ("NSWindow should only be instantiated on the
    main thread", layout-engine corruption warnings), since AppKit is not
    safe to touch off the main thread. do() must now return a presenter
    tuple and do nothing else UI-related; only _async_finished (marshaled
    to the main thread) may call rumps.

    Bypasses the real background thread/AppHelper.callAfter machinery on
    purpose — that needs a live run loop pumping, which a plain pytest
    process doesn't have — and instead runs do() synchronously so this
    test only has to trust threading.Thread itself, not reinvent it.
    """
    from collaborate.menubar_model import build_entries

    calls = []
    monkeypatch.setattr(menubar_app.rumps, "notification", lambda *a: calls.append(("notify", a)))
    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a: calls.append(("alert", a)))
    monkeypatch.setattr(menubar_app, "get_launcher", lambda: _FakeSuccessfulLauncher())

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))

    entry = build_entries(app.repo_path)[0]
    handler = app._make_checkout(entry)
    handler(None)

    assert calls == [], "do() must not call rumps directly — only _async_finished may"
    result = captured[0]
    assert result[0] == "notify"
    assert result[1:3] == ("Collaborate", "MyProject")

    # and the real git/lock side effect actually happened
    from collaborate import locking
    lock = locking.Lock.load(locking.lock_path_for(entry.path))
    assert lock.is_held_by("alice@example.com")


def test_async_finished_dispatches_by_kind_and_always_refreshes(tmp_path, monkeypatch):
    """The main-thread-only half of the same contract: _async_finished must
    route "notify" to a title flash and "alert" to rumps.alert, clear the
    busy flag, and always refresh — this is what AppHelper.callAfter
    marshals do()'s return value into once the background thread finishes.

    "notify" no longer calls rumps.notification() at all (see the
    dedicated regression test below for why) — it flashes the menu bar
    title instead, which has no OS dependency to fail."""
    calls = []
    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a: calls.append(("alert", a)))

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=None)  # refresh() no-ops harmlessly without a repo
    app._busy = True

    app._async_finished(("notify", "Collaborate", "MyProject", "done"))
    assert app.title == " ✓ MyProject"
    assert app._busy is False

    app._busy = True
    app._async_finished(("alert", "Collaborate", "oops"))
    assert calls == [("alert", ("Collaborate", "oops"))]
    assert app._busy is False


def test_notify_never_calls_rumps_notification(monkeypatch):
    """Regression: rumps.notification requires a real .app bundle identity
    (a CFBundleIdentifier from an actual Info.plist) to register with the
    OS notification center — something a bare script run via the `collab`
    console script structurally cannot have. It failed outright in the
    field ("Failed to setup the notification center... missing
    CFBundleIdentifier"), and because that used to run before refresh(), a
    checkout/checkin that genuinely succeeded never showed up as such in
    the menu — indistinguishable from having failed. "notify" must not
    depend on it at all anymore."""
    def must_not_be_called(*_a):
        raise AssertionError("rumps.notification should never be called")

    monkeypatch.setattr(menubar_app.rumps, "notification", must_not_be_called)
    refreshed = []

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=None)
    monkeypatch.setattr(app, "refresh", lambda: refreshed.append(True))
    app._busy = True

    app._async_finished(("notify", "Collaborate", "MyProject", "Checked out"))

    assert refreshed == [True]
    assert app._busy is False
    assert app.title == " ✓ MyProject"


def test_new_project_from_template(alice, tmp_path, monkeypatch):
    """do() for New Project must not call rumps directly, must create the
    project from the configured template, commit+push it, and claim the
    lock — mirroring `collab new`'s template flow."""
    template = tmp_path / "HouseStyle.prproj"
    template.write_text("TEMPLATE CONTENT\n")
    cfg = config_mod.Config.load(alice)
    cfg.template_path = str(template)
    cfg.save(alice)

    calls = []
    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a, **kw: calls.append(("alert", a)))
    monkeypatch.setattr(menubar_app, "get_launcher", lambda: _FakeSuccessfulLauncher())

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    monkeypatch.setattr(app, "_prompt_text", lambda *a, **kw: "NewShow")
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))

    handler = app._make_new_project()
    handler(None)

    assert calls == [], "do() must not call rumps directly"
    result = captured[0]
    assert result[0] == "notify"
    assert result[1:3] == ("Collaborate", "NewShow")

    created = alice / "NewShow.prproj"
    assert created.read_text() == "TEMPLATE CONTENT\n"
    lock = locking.Lock.load(locking.lock_path_for(created))
    assert lock.is_held_by("alice@example.com")


def test_new_project_no_template_points_to_terminal(alice, monkeypatch):
    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    monkeypatch.setattr(app, "_prompt_text", lambda *a, **kw: "NewShow")
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))

    handler = app._make_new_project()
    handler(None)

    result = captured[0]
    assert result[0] == "alert"
    assert "collab new NewShow" in result[2]
    assert not (alice / "NewShow.prproj").exists()


def test_new_project_cancelled_prompt_does_nothing(alice, monkeypatch):
    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    monkeypatch.setattr(app, "_prompt_text", lambda *a, **kw: None)
    called = []
    monkeypatch.setattr(app, "_run_async", lambda fn: called.append(fn))

    handler = app._make_new_project()
    handler(None)
    assert called == []


def test_locked_info_add_note(alice, bob, monkeypatch):
    runner.invoke(cli_app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    sync_repo(bob)
    entry = build_entries(bob)[0]
    assert entry.status == "locked"

    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a, **kw: 1)  # "Add Note…" clicked

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(bob))
    monkeypatch.setattr(app, "_prompt_text", lambda *a, **kw: "please sync audio")
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))

    handler = app._make_locked_info(entry)
    handler(None)

    result = captured[0]
    assert result[0] == "notify"
    assert result[3] == "Note added."

    tix = tickets_mod.load_all(entry.path)
    assert len(tix) == 1
    assert tix[0].text == "please sync audio"


def test_locked_info_ok_does_not_prompt_or_add_note(alice, bob, monkeypatch):
    runner.invoke(cli_app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    sync_repo(bob)
    entry = build_entries(bob)[0]

    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a, **kw: 0)  # "OK" clicked (dismiss)

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(bob))

    def _should_not_be_called(*_a, **_kw):
        raise AssertionError("must not prompt for a note when the alert was just dismissed")

    monkeypatch.setattr(app, "_prompt_text", _should_not_be_called)
    called = []
    monkeypatch.setattr(app, "_run_async", lambda fn: called.append(fn))

    handler = app._make_locked_info(entry)
    handler(None)
    assert called == []
    assert tickets_mod.load_all(entry.path) == []


def test_checkin_with_message_and_keep_lock(alice, monkeypatch):
    runner.invoke(cli_app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    entry = build_entries(alice)[0]
    entry.path.write_text("simulated edit in Premiere\n")  # a real dirty file to actually commit

    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a, **kw: 1)  # "have you saved" -> Yes
    monkeypatch.setattr(menubar_app.rumps, "Window", lambda **kw: _FakeWindow(clicked=2, text="fixed audio sync"))

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))

    handler = app._make_checkin(entry)
    handler(None)

    result = captured[0]
    assert result[0] == "notify"
    assert "lock kept" in result[3].lower()

    lock = locking.Lock.load(locking.lock_path_for(entry.path))
    assert lock.is_held_by("alice@example.com"), "keep_lock=True must not release"

    import subprocess
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=str(alice), capture_output=True, text=True, check=True
    ).stdout
    assert "fixed audio sync" in log


def test_checkin_default_message_and_release(alice, monkeypatch):
    runner.invoke(cli_app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    entry = build_entries(alice)[0]

    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a, **kw: 1)
    monkeypatch.setattr(menubar_app.rumps, "Window", lambda **kw: _FakeWindow(clicked=1, text=""))

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))

    handler = app._make_checkin(entry)
    handler(None)

    result = captured[0]
    assert "released" in result[3].lower()

    lock = locking.Lock.load(locking.lock_path_for(entry.path))
    assert lock.status == "unlocked"


def test_checkin_cancel_button_does_nothing(alice, monkeypatch):
    runner.invoke(cli_app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    entry = build_entries(alice)[0]

    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a, **kw: 1)
    monkeypatch.setattr(menubar_app.rumps, "Window", lambda **kw: _FakeWindow(clicked=0, text=""))

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    called = []
    monkeypatch.setattr(app, "_run_async", lambda fn: called.append(fn))

    handler = app._make_checkin(entry)
    handler(None)
    assert called == []

    lock = locking.Lock.load(locking.lock_path_for(entry.path))
    assert lock.is_held_by("alice@example.com")


def test_refresh_flashes_title_when_someone_else_frees_a_project(alice, bob):
    """Integration of menubar_model.freed_by_others into refresh(): a
    project that was locked by someone else on the last refresh and is
    now free should flash the title, even though nothing we did caused it."""
    runner.invoke(cli_app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(bob))
    app.refresh()  # first refresh: sees it locked by alice, caches that

    runner.invoke(cli_app, ["checkin", "MyProject", "--repo", str(alice)], input="y\n")

    app.refresh()  # second refresh: alice's checkin should now show as freed
    assert "MyProject" in app.title
    assert "✓" in app.title


def test_run_palette_action_checkout(alice, monkeypatch):
    from collaborate.menubar_model import PaletteAction

    monkeypatch.setattr(menubar_app, "get_launcher", lambda: _FakeSuccessfulLauncher())

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))

    entry = build_entries(alice)[0]
    app._run_palette_action(PaletteAction("Check out", entry.name, entry))

    result = captured[0]
    assert result[0] == "notify"
    assert result[1:3] == ("Collaborate", "MyProject")
    lock = locking.Lock.load(locking.lock_path_for(entry.path))
    assert lock.is_held_by("alice@example.com")


def test_run_palette_action_checkin(alice, monkeypatch):
    from collaborate.menubar_model import PaletteAction

    runner.invoke(cli_app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    entry = build_entries(alice)[0]

    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a, **kw: 1)
    monkeypatch.setattr(menubar_app.rumps, "Window", lambda **kw: _FakeWindow(clicked=1, text=""))

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))
    app._run_palette_action(PaletteAction("Check in", entry.name, entry))

    result = captured[0]
    assert "released" in result[3].lower()


def test_run_palette_action_add_note_skips_the_confirming_alert(alice, bob, monkeypatch):
    """The palette's "Add note" already expresses explicit intent (you
    searched for and selected it) — unlike the locked-project menu click,
    it must go straight to the text prompt, not show the "locked by X...
    Add Note/OK" alert first."""
    from collaborate.menubar_model import PaletteAction

    runner.invoke(cli_app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    sync_repo(bob)
    entry = build_entries(bob)[0]

    def _must_not_be_called(*_a, **_kw):
        raise AssertionError("Add note from the palette must not show the confirming alert")

    monkeypatch.setattr(menubar_app.rumps, "alert", _must_not_be_called)

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(bob))
    monkeypatch.setattr(app, "_prompt_text", lambda *a, **kw: "please sync audio")
    captured = []
    monkeypatch.setattr(app, "_run_async", lambda fn: captured.append(fn()))

    app._run_palette_action(PaletteAction("Add note", entry.name, entry))

    result = captured[0]
    assert result[3] == "Note added."
    assert tickets_mod.load_all(entry.path)[0].text == "please sync audio"


def test_open_search_palette_uses_cached_entries_for_instant_open(alice, monkeypatch):
    """_open_search_palette must not do a fresh sync/build — it's meant to
    be instantaneous; the palette action itself does fresh git work
    regardless of whether the snapshot it was opened from was current."""
    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    app._last_entries = "sentinel-cached-entries"

    monkeypatch.setattr(menubar_app, "build_entries", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("must reuse the cached snapshot, not rebuild")
    ))
    shown = []
    monkeypatch.setattr(app._palette, "show", lambda actions: shown.append(actions))
    monkeypatch.setattr(menubar_app, "palette_actions", lambda entries: entries)

    app._open_search_palette()
    assert shown == ["sentinel-cached-entries"]


def test_open_search_palette_builds_fresh_when_nothing_cached_yet(alice):
    """Before the very first refresh (_last_entries is still None), there's
    nothing to reuse — must fall back to a real build_entries() call."""
    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    assert app._last_entries is None

    app._open_search_palette()
    assert [a.project for a in app._palette.visible_actions] == ["MyProject"]


class _FakeEvent:
    """A real NSEvent can't be synthesized in a test process — this is any
    plain object exposing the two methods _is_hotkey_event actually reads."""
    def __init__(self, key_code, modifier_flags):
        self._key_code = key_code
        self._modifier_flags = modifier_flags

    def keyCode(self):
        return self._key_code

    def modifierFlags(self):
        return self._modifier_flags


def test_is_hotkey_event_matches_cmd_shift_c():
    from AppKit import NSEventModifierFlagCommand, NSEventModifierFlagShift

    cmd_shift = NSEventModifierFlagCommand | NSEventModifierFlagShift
    assert menubar_app.OpenDamMenuBarApp._is_hotkey_event(_FakeEvent(key_code=8, modifier_flags=cmd_shift))


def test_is_hotkey_event_rejects_wrong_key_or_modifiers():
    from AppKit import NSEventModifierFlagCommand, NSEventModifierFlagOption, NSEventModifierFlagShift

    cmd_shift = NSEventModifierFlagCommand | NSEventModifierFlagShift
    is_hotkey = menubar_app.OpenDamMenuBarApp._is_hotkey_event

    assert not is_hotkey(_FakeEvent(key_code=1, modifier_flags=cmd_shift)), "wrong key ('S', not 'C')"
    assert not is_hotkey(_FakeEvent(key_code=8, modifier_flags=NSEventModifierFlagCommand)), "missing Shift"
    assert not is_hotkey(
        _FakeEvent(key_code=8, modifier_flags=cmd_shift | NSEventModifierFlagOption)
    ), "an extra held modifier (Option) must not still match"


def test_hotkey_registration_does_not_raise(alice):
    """Registration must never crash even without Accessibility/Input
    Monitoring permission granted — it should just silently end up
    non-functional (the handler never fires), which is the whole point of
    also having the "Search…" menu item as a guaranteed-to-work fallback."""
    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=str(alice))
    app._register_global_hotkey()  # must not raise
