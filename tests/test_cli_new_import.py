from pathlib import Path

from typer.testing import CliRunner

from opendam import cli, config as config_mod
from opendam.locking import Lock, lock_path_for

runner = CliRunner()


class FakeLauncher:
    """Stands in for a real Premiere launch during tests — records calls and,
    for launch_blank, can simulate "the user saved a new project" by writing
    a file, since that's what a real Premiere session would do."""

    def __init__(self, write_on_blank_launch=None):
        self.launched = []
        self.launched_blank = 0
        self._write_on_blank_launch = write_on_blank_launch

    def launch(self, prproj_path, app_path):
        self.launched.append(prproj_path)

    def launch_blank(self, app_path):
        self.launched_blank += 1
        if self._write_on_blank_launch:
            self._write_on_blank_launch.write_text("saved via fake premiere\n")

    def is_running(self):
        return False


def _set_template(repo, template_path):
    cfg = config_mod.Config.load(repo)
    cfg.template_path = str(template_path)
    cfg.save(repo)


def test_new_from_template(alice, tmp_path, monkeypatch):
    template = tmp_path / "HouseStyle.prproj"
    template.write_text("TEMPLATE CONTENT\n")
    _set_template(alice, template)

    fake = FakeLauncher()
    monkeypatch.setattr(cli, "get_launcher", lambda: fake)

    result = runner.invoke(cli.app, ["new", "NewShow", "--repo", str(alice)])
    assert result.exit_code == 0, result.output

    created = alice / "NewShow.prproj"
    assert created.read_text() == "TEMPLATE CONTENT\n"
    lock = Lock.load(lock_path_for(created))
    assert lock.status == "locked"
    assert lock.locked_by["user"] == "alice@example.com"
    assert fake.launched == [created]

    log = _log(alice)
    assert any("new project: NewShow.prproj" in line for line in log)


def test_new_without_template_waits_for_manual_save(alice, monkeypatch):
    target = alice / "HandMade.prproj"
    fake = FakeLauncher(write_on_blank_launch=target)
    monkeypatch.setattr(cli, "get_launcher", lambda: fake)

    result = runner.invoke(cli.app, ["new", "HandMade", "--repo", str(alice)], input="y\n")
    assert result.exit_code == 0, result.output
    assert fake.launched_blank == 1
    assert target.exists()
    lock = Lock.load(lock_path_for(target))
    assert lock.status == "locked"


def test_new_without_template_no_save_aborts(alice, monkeypatch):
    fake = FakeLauncher()  # never writes the file
    monkeypatch.setattr(cli, "get_launcher", lambda: fake)

    result = runner.invoke(cli.app, ["new", "Ghost", "--repo", str(alice)], input="y\n")
    assert result.exit_code != 0
    assert not (alice / "Ghost.prproj").exists()


def test_new_collides_with_existing_file(alice, monkeypatch):
    (alice / "MyProject.prproj").exists()  # already seeded by the fixture
    result = runner.invoke(cli.app, ["new", "MyProject", "--repo", str(alice)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_import_copies_and_keeps_source(alice, tmp_path, monkeypatch):
    fake = FakeLauncher()
    monkeypatch.setattr(cli, "get_launcher", lambda: fake)
    source = tmp_path / "Legacy.prproj"
    source.write_text("legacy contents\n")

    result = runner.invoke(cli.app, ["import", str(source), "--repo", str(alice)])
    assert result.exit_code == 0, result.output

    imported = alice / "Legacy.prproj"
    assert imported.read_text() == "legacy contents\n"
    assert source.exists()  # not moved by default
    # no --checkout, so no lock was ever claimed — no lock file at all,
    # which reads as "unlocked" the same as any never-locked project.
    assert not lock_path_for(imported).exists()
    assert fake.launched == []


def test_import_with_move_and_checkout(alice, tmp_path, monkeypatch):
    fake = FakeLauncher()
    monkeypatch.setattr(cli, "get_launcher", lambda: fake)
    source = tmp_path / "Legacy2.prproj"
    source.write_text("legacy contents 2\n")

    result = runner.invoke(
        cli.app,
        ["import", str(source), "Renamed", "--repo", str(alice), "--move", "--checkout"],
    )
    assert result.exit_code == 0, result.output

    imported = alice / "Renamed.prproj"
    assert imported.exists()
    assert not source.exists()  # removed by --move
    lock = Lock.load(lock_path_for(imported))
    assert lock.status == "locked"
    assert lock.locked_by["user"] == "alice@example.com"
    assert fake.launched == [imported]


def test_new_on_empty_remote(empty_remote_clone, tmp_path, monkeypatch):
    """First-ever project in a freshly created (never-pushed) remote repo —
    there's no remote branch to pull yet, which must not crash; the first
    push creates it."""
    template = tmp_path / "HouseStyle.prproj"
    template.write_text("TEMPLATE CONTENT\n")
    _set_template(empty_remote_clone, template)

    fake = FakeLauncher()
    monkeypatch.setattr(cli, "get_launcher", lambda: fake)

    result = runner.invoke(cli.app, ["new", "FirstEver", "--repo", str(empty_remote_clone)])
    assert result.exit_code == 0, result.output

    created = empty_remote_clone / "FirstEver.prproj"
    lock = Lock.load(lock_path_for(created))
    assert lock.status == "locked"
    # and the push actually created the remote branch
    import subprocess
    heads = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=str(empty_remote_clone), capture_output=True, text=True, check=True,
    ).stdout
    assert "refs/heads/" in heads


def _log(repo: Path) -> list[str]:
    import subprocess
    result = subprocess.run(
        ["git", "log", "--oneline"], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()
