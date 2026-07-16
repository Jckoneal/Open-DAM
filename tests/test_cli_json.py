import json

from typer.testing import CliRunner

from opendam.cli import app

runner = CliRunner()


def test_list_json_unlocked(alice):
    result = runner.invoke(app, ["list", "--json", "--repo", str(alice)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data["projects"]) == 1
    p = data["projects"][0]
    assert p["name"] == "MyProject"
    assert p["status"] == "unlocked"
    assert p["locked_by"] is None
    assert p["mine"] is False
    assert p["path"].endswith("MyProject.prproj")


def test_list_json_shows_mine_flag(alice, bob):
    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    assert result.exit_code == 0, result.output

    mine = json.loads(runner.invoke(app, ["list", "--json", "--repo", str(alice)]).output)["projects"][0]
    assert mine["status"] == "locked"
    assert mine["mine"] is True
    assert mine["locked_by"] == "alice@example.com"

    theirs = json.loads(runner.invoke(app, ["list", "--json", "--repo", str(bob)]).output)["projects"][0]
    assert theirs["status"] == "locked"
    assert theirs["mine"] is False


def test_checkin_yes_skips_confirmation(alice):
    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    assert result.exit_code == 0, result.output

    # no input= provided: would hang/abort on the confirm prompt without --yes
    result = runner.invoke(app, ["checkin", "MyProject", "--repo", str(alice), "--yes"])
    assert result.exit_code == 0, result.output
    assert "released the lock" in result.output
