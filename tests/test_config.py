from opendam.config import Config


def test_load_recovers_from_legacy_bare_premiere_string(tmp_path):
    """`dam config set premiere <path>` used to overwrite the whole `premiere`
    section with a plain string instead of a mapping, which crashed every
    later Config.load() with `PremiereConfig() argument after ** must be a
    mapping, not str`. Loading must tolerate an already-corrupted file."""
    (tmp_path / ".damconfig.yaml").write_text(
        "schema_version: 1\n"
        "remote: null\n"
        "media_root: null\n"
        "premiere: /Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app\n"
        "stale_lock_hours: 24\n"
    )
    cfg = Config.load(tmp_path)
    assert cfg.premiere.app_path == "/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app"


def test_load_ignores_unknown_premiere_keys(tmp_path):
    (tmp_path / ".damconfig.yaml").write_text(
        "premiere:\n  app_path: /some/path\n  future_field: surprise\n"
    )
    cfg = Config.load(tmp_path)
    assert cfg.premiere.app_path == "/some/path"
