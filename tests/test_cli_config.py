from typer.testing import CliRunner

from collaborate.cli import app
from collaborate.config import Config

runner = CliRunner()


def test_config_set_bare_premiere_rejected(alice):
    result = runner.invoke(app, ["config", "set", "premiere", "/some/app.app", "--repo", str(alice)])
    assert result.exit_code != 0
    assert "not a settable value" in result.output
    # must not have written a corrupting value — file shouldn't even exist yet
    assert not (alice / ".collabconfig.yaml").exists()


def test_config_set_and_get_premiere_app_path(alice):
    result = runner.invoke(
        app, ["config", "set", "premiere.app_path", "/some/app.app", "--repo", str(alice)]
    )
    assert result.exit_code == 0, result.output

    cfg = Config.load(alice)
    assert cfg.premiere.app_path == "/some/app.app"

    result = runner.invoke(app, ["config", "get", "premiere.app_path", "--repo", str(alice)])
    assert result.exit_code == 0, result.output
    assert "/some/app.app" in result.output


def test_config_set_unknown_key_rejected(alice):
    result = runner.invoke(app, ["config", "set", "media_rot", "/tmp", "--repo", str(alice)])
    assert result.exit_code != 0
    assert "Unknown config key" in result.output


def test_config_get_unknown_key_fails_cleanly(alice):
    result = runner.invoke(app, ["config", "get", "nonexistent.thing", "--repo", str(alice)])
    assert result.exit_code != 0
    assert "Unknown config key" in result.output


def test_config_set_cleans_shell_escaped_paths(alice):
    result = runner.invoke(
        app,
        ["config", "set", "media_root", "/Volumes/Jacks\\ SSD\\ 2 ", "--repo", str(alice)],
    )
    assert result.exit_code == 0, result.output
    cfg = Config.load(alice)
    assert cfg.media_root == "/Volumes/Jacks SSD 2"


def test_commands_outside_a_git_repo_fail_cleanly(tmp_path):
    """Running any command (e.g. `collab init` from the home directory) in a
    place that isn't a git repo must give a clear error, not a traceback
    from whatever git call happens to run first."""
    not_a_repo = tmp_path / "just_a_folder"
    not_a_repo.mkdir()
    result = runner.invoke(app, ["list", "--repo", str(not_a_repo)])
    assert result.exit_code != 0
    # Rich wraps long lines (the tmp_path here is long) to the detected
    # console width, which can split this phrase across a line break —
    # flatten whitespace before checking, same fix as tests/test_tickets.py.
    assert "not inside a project library" in " ".join(result.output.split())
