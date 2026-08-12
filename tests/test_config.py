from collaborate import config as config_mod
from collaborate.config import Config


def _fake_bundle(tmp_path, with_template=True):
    """A minimal Contents/MacOS + Contents/Resources tree mimicking what
    py2app actually produces, so _bundled_resource_path's Contents/MacOS/x
    -> ../Resources/ path math can be exercised for real."""
    macos = tmp_path / "Collaborate.app" / "Contents" / "MacOS"
    resources = tmp_path / "Collaborate.app" / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    executable = macos / "Collaborate"
    executable.write_text("")
    if with_template:
        (resources / config_mod.DEFAULT_TEMPLATE_RESOURCE).write_text("fake bundled template\n")
    return executable


def test_bundled_template_used_when_frozen_and_unconfigured(tmp_path, monkeypatch):
    executable = _fake_bundle(tmp_path)
    monkeypatch.setattr(config_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_mod.sys, "executable", str(executable))

    repo = tmp_path / "library"
    repo.mkdir()
    cfg = Config.load(repo)
    assert cfg.template_path == str(tmp_path / "Collaborate.app" / "Contents" / "Resources" / "Template.prproj")


def test_bundled_template_not_used_when_not_frozen(tmp_path, monkeypatch):
    _fake_bundle(tmp_path)
    monkeypatch.delattr(config_mod.sys, "frozen", raising=False)

    repo = tmp_path / "library"
    repo.mkdir()
    cfg = Config.load(repo)
    assert cfg.template_path is None


def test_bundled_template_absent_returns_none(tmp_path, monkeypatch):
    executable = _fake_bundle(tmp_path, with_template=False)
    monkeypatch.setattr(config_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_mod.sys, "executable", str(executable))

    repo = tmp_path / "library"
    repo.mkdir()
    cfg = Config.load(repo)
    assert cfg.template_path is None


def test_explicit_template_path_never_overridden_by_bundled_fallback(tmp_path, monkeypatch):
    executable = _fake_bundle(tmp_path)
    monkeypatch.setattr(config_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_mod.sys, "executable", str(executable))

    repo = tmp_path / "library"
    repo.mkdir()
    (repo / config_mod.CONFIG_FILENAME).write_text("template_path: /Volumes/EDIT_SSD/HouseStyle.prproj\n")

    cfg = Config.load(repo)
    assert cfg.template_path == "/Volumes/EDIT_SSD/HouseStyle.prproj"


def test_load_recovers_from_legacy_bare_premiere_string(tmp_path):
    """`collab config set premiere <path>` used to overwrite the whole `premiere`
    section with a plain string instead of a mapping, which crashed every
    later Config.load() with `PremiereConfig() argument after ** must be a
    mapping, not str`. Loading must tolerate an already-corrupted file."""
    (tmp_path / ".collabconfig.yaml").write_text(
        "schema_version: 1\n"
        "remote: null\n"
        "media_root: null\n"
        "premiere: /Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app\n"
        "stale_lock_hours: 24\n"
    )
    cfg = Config.load(tmp_path)
    assert cfg.premiere.app_path == "/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app"


def test_load_ignores_unknown_premiere_keys(tmp_path):
    (tmp_path / ".collabconfig.yaml").write_text(
        "premiere:\n  app_path: /some/path\n  future_field: surprise\n"
    )
    cfg = Config.load(tmp_path)
    assert cfg.premiere.app_path == "/some/path"
