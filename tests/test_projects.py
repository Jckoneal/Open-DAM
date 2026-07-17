from typer.testing import CliRunner

from opendam import projects as projects_mod
from opendam.cli import app

runner = CliRunner()

RESCUE_NAME = "MyProject--edebf705-968c-ecbf-0133-5b6fdc57dd20-2026-07-15_22-20-28.prproj"


def test_discover_ignores_premiere_autosave_artifacts(alice):
    autosave_dir = alice / "Adobe Premiere Pro Auto-Save"
    autosave_dir.mkdir()
    (autosave_dir / "MyProject-2026-07-15_22-20-28.prproj").write_text("autosave\n")
    # rescue copies can also land next to the real project, outside the folder
    (alice / RESCUE_NAME).write_text("rescue copy\n")

    names = [p.name for p in projects_mod.discover(alice)]
    assert names == ["MyProject"]

    result = runner.invoke(app, ["list", "--repo", str(alice)])
    assert result.exit_code == 0, result.output
    assert "edebf705" not in result.output
    assert "Auto-Save" not in result.output


def test_normal_projects_in_subfolders_still_discovered(alice):
    sub = alice / "Season2"
    sub.mkdir()
    (sub / "Ep05.prproj").write_text("real project\n")

    names = sorted(p.name for p in projects_mod.discover(alice))
    assert names == ["Ep05", "MyProject"]
