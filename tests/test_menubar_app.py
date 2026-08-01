"""Tests for the rumps-specific app layer. Skipped entirely when the
optional `menubar` extra (rumps/pyobjc) isn't installed — menubar_model.py
carries all the logic that can (and must) be tested without it; this file
covers only the thin rumps glue on top."""

import inspect

import pytest

rumps = pytest.importorskip("rumps")

from opendam import menubar_app
from opendam.menubar_model import AppSettings


class _FakeSuccessfulLauncher:
    def launch(self, *_a, **_kw):
        pass


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
    from opendam.menubar_model import build_entries

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
    assert result[1:3] == ("Open-DAM", "MyProject")

    # and the real git/lock side effect actually happened
    from opendam import locking
    lock = locking.Lock.load(locking.lock_path_for(entry.path))
    assert lock.is_held_by("alice@example.com")


def test_async_finished_dispatches_by_kind_and_always_refreshes(tmp_path, monkeypatch):
    """The main-thread-only half of the same contract: _async_finished must
    route "notify"/"alert" tuples to the matching rumps call, clear the
    busy flag, and always refresh — this is what AppHelper.callAfter
    marshals do()'s return value into once the background thread finishes."""
    calls = []
    monkeypatch.setattr(menubar_app.rumps, "notification", lambda *a: calls.append(("notify", a)))
    monkeypatch.setattr(menubar_app.rumps, "alert", lambda *a: calls.append(("alert", a)))

    app = menubar_app.OpenDamMenuBarApp()
    app.settings = AppSettings(repo_path=None)  # refresh() no-ops harmlessly without a repo
    app._busy = True

    app._async_finished(("notify", "Open-DAM", "Ep01", "done"))
    assert calls == [("notify", ("Open-DAM", "Ep01", "done"))]
    assert app._busy is False

    calls.clear()
    app._busy = True
    app._async_finished(("alert", "Open-DAM", "oops"))
    assert calls == [("alert", ("Open-DAM", "oops"))]
    assert app._busy is False
