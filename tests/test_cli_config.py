from typer.testing import CliRunner

from opendam.cli import app
from opendam.config import Config

runner = CliRunner()


def test_config_set_bare_premiere_rejected(alice):
    result = runner.invoke(app, ["config", "set", "premiere", "/some/app.app", "--repo", str(alice)])
    assert result.exit_code != 0
    assert "not a settable value" in result.output
    # must not have written a corrupting value — file shouldn't even exist yet
    assert not (alice / ".damconfig.yaml").exists()


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
