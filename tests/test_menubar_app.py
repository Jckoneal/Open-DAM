"""Tests for the rumps-specific app layer. Skipped entirely when the
optional `menubar` extra (rumps/pyobjc) isn't installed — menubar_model.py
carries all the logic that can (and must) be tested without it; this file
covers only the thin rumps glue on top."""

import inspect

import pytest

rumps = pytest.importorskip("rumps")

from opendam import menubar_app
from opendam.menubar_model import AppSettings


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
