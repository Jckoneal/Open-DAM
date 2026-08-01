"""Per-machine `.collabconfig.yaml` at the project library root. Gitignored —
it travels with a given clone, not with the shared history, since remote URL
access method and local paths differ per person's machine."""

from __future__ import annotations

import glob
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CONFIG_FILENAME = ".collabconfig.yaml"
DEFAULT_STALE_LOCK_HOURS = 24


@dataclass
class PremiereConfig:
    app_path: Optional[str] = None
    exe_path: Optional[str] = None


@dataclass
class Config:
    schema_version: int = 1
    remote: Optional[str] = None
    media_root: Optional[str] = None
    premiere: PremiereConfig = field(default_factory=PremiereConfig)
    stale_lock_hours: int = DEFAULT_STALE_LOCK_HOURS
    template_path: Optional[str] = None

    @classmethod
    def load(cls, repo: Path) -> "Config":
        path = repo / CONFIG_FILENAME
        if not path.exists():
            return cls()
        raw = yaml.safe_load(path.read_text()) or {}
        premiere_raw = raw.pop("premiere", {}) or {}
        if isinstance(premiere_raw, str):
            # Recovers from a pre-fix `collab config set premiere <path>` (the
            # bare key, not `premiere.app_path`), which used to overwrite
            # this whole section with a plain string instead of a mapping.
            premiere_raw = {"app_path": premiere_raw}
        elif not isinstance(premiere_raw, dict):
            premiere_raw = {}
        cfg = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        cfg.premiere = PremiereConfig(
            **{k: v for k, v in premiere_raw.items() if k in PremiereConfig.__dataclass_fields__}
        )
        return cfg

    def save(self, repo: Path) -> None:
        path = repo / CONFIG_FILENAME
        data = asdict(self)
        path.write_text(yaml.safe_dump(data, sort_keys=False))


def discover_premiere_macos() -> list[str]:
    """Glob /Applications for installed Premiere Pro versions."""
    candidates = sorted(glob.glob("/Applications/Adobe Premiere Pro*/Adobe Premiere Pro*.app"))
    if candidates:
        return candidates
    try:
        out = subprocess.run(
            ["mdfind", "kMDItemCFBundleIdentifier == 'com.adobe.PremierePro.*'"],
            capture_output=True, text=True, timeout=10,
        )
        return [line for line in out.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, OSError):
        return []


def discover_premiere() -> list[str]:
    if platform.system() == "Darwin":
        return discover_premiere_macos()
    return []
