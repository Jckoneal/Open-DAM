from typer.testing import CliRunner

from collaborate import tickets as tickets_mod
from collaborate.cli import app

runner = CliRunner()


def _project(repo):
    return repo / "MyProject.prproj"


def _flat(text: str) -> str:
    """Collapse whitespace/newlines. Rich wraps console/table output to the
    detected terminal width, which is environment-dependent and can insert a
    line break mid-phrase — asserting on a multi-word substring directly is
    flaky; flatten first so wrapping can't split what we're looking for."""
    return " ".join(text.split())


def test_add_ticket_without_holding_lock(alice, bob):
    # alice holds the lock...
    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    assert result.exit_code == 0, result.output

    # ...but bob can still add a ticket
    result = runner.invoke(
        app, ["ticket", "add", "MyProject", "Fix audio sync at 02:14", "--repo", str(bob)]
    )
    assert result.exit_code == 0, result.output
    ticket = tickets_mod.load_all(_project(bob))[0]
    # id must be visible (rich eats [brackets] as markup unless escaped)
    assert f"[{ticket.id}]" in result.output

    # and alice sees it after her next ticket list (which syncs)
    result = runner.invoke(app, ["ticket", "list", "MyProject", "--repo", str(alice)])
    assert result.exit_code == 0, result.output
    assert "Fix audio sync" in _flat(result.output)
    assert "open" in result.output


def test_concurrent_adds_from_stale_clones_both_survive(alice, bob):
    result = runner.invoke(app, ["ticket", "add", "MyProject", "alice note", "--repo", str(alice)])
    assert result.exit_code == 0, result.output

    # bob's clone is now stale (hasn't pulled alice's ticket) but adds anyway —
    # per-ticket files mean the rebase-retry push integrates cleanly
    result = runner.invoke(app, ["ticket", "add", "MyProject", "bob note", "--repo", str(bob)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["ticket", "list", "MyProject", "--repo", str(alice)])
    flat = _flat(result.output)
    assert "alice note" in flat
    assert "bob note" in flat


def test_checkin_succeeds_after_remote_advanced_during_session(alice, bob):
    """Regression: checkin used to run `pull --ff-only` after committing,
    which can never fast-forward once the remote moved (e.g. someone added a
    ticket) while local commits exist — it crashed with 'Diverging branches'."""
    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    assert result.exit_code == 0, result.output

    # remote advances while alice is editing
    result = runner.invoke(app, ["ticket", "add", "MyProject", "mid-session note", "--repo", str(bob)])
    assert result.exit_code == 0, result.output

    (_project(alice)).write_text("alice edit\n")
    result = runner.invoke(app, ["checkin", "MyProject", "--repo", str(alice)], input="y\n")
    assert result.exit_code == 0, result.output
    assert "released the lock" in result.output

    # both alice's edit and bob's ticket survived
    result = runner.invoke(app, ["ticket", "list", "MyProject", "--repo", str(alice)])
    assert "mid-session note" in _flat(result.output)


def test_ticket_done_by_prefix(alice):
    runner.invoke(app, ["ticket", "add", "MyProject", "Color pass scene 3", "--repo", str(alice)])
    ticket = tickets_mod.load_all(_project(alice))[0]

    result = runner.invoke(
        app, ["ticket", "done", "MyProject", ticket.id[:4], "--repo", str(alice)]
    )
    assert result.exit_code == 0, result.output
    assert "Closed ticket" in result.output

    reloaded = tickets_mod.load_all(_project(alice))[0]
    assert reloaded.status == "done"
    assert reloaded.done_by["user"] == "alice@example.com"

    # already done → friendly no-op
    result = runner.invoke(app, ["ticket", "done", "MyProject", ticket.id, "--repo", str(alice)])
    assert result.exit_code == 0
    assert "already done" in result.output


def test_ticket_done_unknown_and_ambiguous_prefix(alice):
    result = runner.invoke(app, ["ticket", "done", "MyProject", "zzzz", "--repo", str(alice)])
    assert result.exit_code != 0
    assert "No ticket starting with" in result.output


def test_checkin_note_creates_ticket_in_checkin_commit(alice, bob):
    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    assert result.exit_code == 0, result.output
    (_project(alice)).write_text("edited\n")

    result = runner.invoke(
        app,
        ["checkin", "MyProject", "--repo", str(alice), "--note", "rough cut done, needs color"],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert "Left ticket" in result.output

    # bob checks out next and is shown the note
    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(bob), "--no-launch"])
    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    assert "rough cut done, needs color" in flat
    assert "To do on this project" in flat


def test_list_shows_open_ticket_count(alice):
    runner.invoke(app, ["ticket", "add", "MyProject", "note one", "--repo", str(alice)])
    runner.invoke(app, ["ticket", "add", "MyProject", "note two", "--repo", str(alice)])

    result = runner.invoke(app, ["list", "--repo", str(alice)])
    assert result.exit_code == 0, result.output
    assert "Todo" in result.output
    assert "2" in result.output

    # closing one drops the count
    first = tickets_mod.load_all(_project(alice))[0]
    runner.invoke(app, ["ticket", "done", "MyProject", first.id, "--repo", str(alice)])
    result = runner.invoke(app, ["list", "--repo", str(alice)])
    assert "1" in result.output


def test_ticket_list_open_only_filter(alice):
    runner.invoke(app, ["ticket", "add", "MyProject", "will be closed", "--repo", str(alice)])
    runner.invoke(app, ["ticket", "add", "MyProject", "stays open", "--repo", str(alice)])
    first = tickets_mod.load_all(_project(alice))[0]
    runner.invoke(app, ["ticket", "done", "MyProject", first.id, "--repo", str(alice)])

    result = runner.invoke(app, ["ticket", "list", "MyProject", "--open", "--repo", str(alice)])
    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    assert "stays open" in flat
    assert "will be closed" not in flat
