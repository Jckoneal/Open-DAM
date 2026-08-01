"""Tests for the pure menu-bar logic. Deliberately does not import rumps —
this module must be testable (and is) without the `menubar` extra installed."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from collaborate import locking
from collaborate import menubar_model as mb
from collaborate.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def _iso(minutes_ago: int) -> str:
    then = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return then.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def test_elapsed_label():
    assert mb.elapsed_label(None) == ""
    assert mb.elapsed_label(_iso(0)) == ""  # fresh lock: no noisy "0m"
    assert mb.elapsed_label(_iso(14)) == "14m"
    assert mb.elapsed_label(_iso(134)) == "2h 14m"
    assert mb.elapsed_label(_iso(240)) == "4h"


def test_is_stale():
    assert mb.is_stale(None) is False
    assert mb.is_stale(_iso(60), stale_lock_hours=24) is False
    assert mb.is_stale(_iso(25 * 60), stale_lock_hours=24) is True


def test_build_entries_flags_stale_lock(alice):
    runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    lock_path = locking.lock_path_for(alice / "MyProject.prproj")
    lock = locking.Lock.load(lock_path)
    lock.locked_at = _iso(25 * 60)  # backdate to simulate a stale checkout
    lock.save(lock_path)

    entry = mb.build_entries(alice, stale_lock_hours=24)[0]
    assert entry.stale is True
    assert "⚠" in entry.label
    assert "25h" in entry.label or "24h" in entry.label  # elapsed shown alongside


def test_group_entries_separates_mine_from_others(alice, bob):
    runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    entries = mb.build_entries(alice)
    mine, others = mb.group_entries(entries)
    assert [e.name for e in mine] == ["MyProject"]
    assert others == []

    mb.sync_repo(bob)
    theirs_entries = mb.build_entries(bob)
    mine, others = mb.group_entries(theirs_entries)
    assert mine == []
    assert [e.name for e in others] == ["MyProject"]


def test_freed_by_others():
    locked = mb.ProjectEntry("Ep01", Path("Ep01.prproj"), "locked", "dana@x.com", _iso(60), 0, False)
    now_free = mb.ProjectEntry("Ep01", Path("Ep01.prproj"), "available", None, None, 0, False)
    still_locked = mb.ProjectEntry("Ep02", Path("Ep02.prproj"), "locked", "dana@x.com", _iso(5), 0, False)

    assert mb.freed_by_others([locked], [now_free]) == ["Ep01"]
    assert mb.freed_by_others([locked], [locked]) == []
    assert mb.freed_by_others([locked, still_locked], [now_free, still_locked]) == ["Ep01"]


def test_check_media_root(tmp_path):
    assert mb.check_media_root(None) is None
    assert mb.check_media_root(str(tmp_path)) is None  # exists -> no warning

    missing = str(tmp_path / "nonexistent")
    warning = mb.check_media_root(missing)
    assert warning is not None
    assert missing in warning


def test_palette_actions_available_and_locked(alice, bob):
    runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    mine_actions = mb.palette_actions(mb.build_entries(alice))
    assert [(a.verb, a.project) for a in mine_actions] == [
        ("Check in", "MyProject"),
        ("Add note", "MyProject"),
    ]
    assert mine_actions[0].label == "Check in — MyProject"

    mb.sync_repo(bob)
    theirs_actions = mb.palette_actions(mb.build_entries(bob))
    assert [(a.verb, a.project) for a in theirs_actions] == [("Add note", "MyProject")]


def test_palette_actions_available_project():
    entry = mb.ProjectEntry("Ep02", Path("Ep02.prproj"), "available", None, None, 0, False)
    actions = mb.palette_actions([entry])
    assert [(a.verb, a.project) for a in actions] == [("Check out", "Ep02")]


def test_filter_actions_matches_project_name_case_insensitively():
    actions = mb.palette_actions([
        mb.ProjectEntry("Ep01_RoughCut", Path("a"), "mine", None, _iso(5), 0, False),
        mb.ProjectEntry("Ep02_Assembly", Path("b"), "available", None, None, 0, False),
        mb.ProjectEntry("Brand_Sizzle", Path("c"), "available", None, None, 0, False),
    ])

    assert [a.project for a in mb.filter_actions(actions, "")] == [
        "Ep01_RoughCut", "Ep01_RoughCut", "Ep02_Assembly", "Brand_Sizzle",
    ]
    assert [a.project for a in mb.filter_actions(actions, "ep0")] == [
        "Ep01_RoughCut", "Ep01_RoughCut", "Ep02_Assembly",
    ]
    assert [a.project for a in mb.filter_actions(actions, "SIZZLE")] == ["Brand_Sizzle"]
    assert mb.filter_actions(actions, "nonexistent") == []


def test_filter_actions_does_not_match_on_verb_text():
    # "check" appears in every verb — must not match every action just
    # because it typed the wrong thing into the project-name filter
    actions = mb.palette_actions([
        mb.ProjectEntry("Ep01", Path("a"), "mine", None, _iso(5), 0, False),
    ])
    assert mb.filter_actions(actions, "check") == []
