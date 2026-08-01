"""Tests for the pure menu-bar logic. Deliberately does not import rumps —
this module must be testable (and is) without the `menubar` extra installed."""

from opendam import menubar_model as mb
from opendam.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_settings_round_trip(tmp_path):
    path = tmp_path / "menubar.json"
    settings = mb.AppSettings(repo_path="/Users/jack/Premiere-Projects")
    settings.save(path)

    reloaded = mb.AppSettings.load(path)
    assert reloaded.repo_path == "/Users/jack/Premiere-Projects"


def test_settings_load_missing_file_returns_defaults(tmp_path):
    settings = mb.AppSettings.load(tmp_path / "does-not-exist.json")
    assert settings.repo_path is None


def test_build_entries_unlocked(alice):
    entries = mb.build_entries(alice)
    assert len(entries) == 1
    assert entries[0].name == "MyProject"
    assert entries[0].status == "available"
    assert entries[0].label == "○ MyProject"


def test_build_entries_mine_vs_locked(alice, bob):
    runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])

    mine = mb.build_entries(alice)[0]
    assert mine.status == "mine"
    assert mine.label == "● MyProject"

    mb.sync_repo(bob)  # the app always syncs before building entries — see refresh()
    theirs = mb.build_entries(bob)[0]
    assert theirs.status == "locked"
    assert theirs.locked_by == "alice@example.com"
    assert "alice@example.com" in theirs.label
    assert "\U0001f512" in theirs.label


def test_build_entries_shows_open_ticket_count(alice):
    runner.invoke(app, ["ticket", "add", "MyProject", "fix audio", "--repo", str(alice)])
    entry = mb.build_entries(alice)[0]
    assert entry.open_tickets == 1
    assert "(1)" in entry.label


def test_sync_repo_returns_none_on_success(alice):
    assert mb.sync_repo(alice) is None


def test_sync_repo_returns_warning_on_unreachable_remote(alice):
    # point origin at a nonexistent remote to force a real failure
    import subprocess
    subprocess.run(["git", "remote", "set-url", "origin", "/nonexistent/path.git"], cwd=str(alice), check=True)
    warning = mb.sync_repo(alice)
    assert warning is not None
    assert "sync" in warning.lower()
