from typer.testing import CliRunner

from opendam.cli import app

runner = CliRunner()


def test_checkout_no_launch_then_checkin(alice):
    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    assert result.exit_code == 0, result.output
    assert "Checked out" in result.output

    result = runner.invoke(
        app, ["checkin", "MyProject", "--repo", str(alice)], input="y\n"
    )
    assert result.exit_code == 0, result.output
    assert "released the lock" in result.output


def test_checkout_blocked_by_other_holder(alice, bob):
    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(alice), "--no-launch"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["checkout", "MyProject", "--repo", str(bob), "--no-launch"])
    assert result.exit_code != 0
    assert "already checked out" in result.output
