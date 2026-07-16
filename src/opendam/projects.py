"""Discovers *.prproj files (and their sibling lock files) in a DAM repo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from opendam.errors import ProjectNotFoundError
from opendam.locking import Lock, lock_path_for


@dataclass
class ProjectInfo:
    name: str  # basename without .prproj
    path: Path
    lock: Optional[Lock]


def discover(repo: Path) -> list[ProjectInfo]:
    projects = []
    for prproj in sorted(repo.rglob("*.prproj")):
        lpath = lock_path_for(prproj)
        lock = Lock.load(lpath) if lpath.exists() else None
        projects.append(ProjectInfo(name=prproj.stem, path=prproj, lock=lock))
    return projects


def find(repo: Path, name: str) -> ProjectInfo:
    """Resolve a project by basename (or relative path if names collide)."""
    all_projects = discover(repo)
    target = name if name.endswith(".prproj") else f"{name}.prproj"

    by_relpath = [p for p in all_projects if str(p.path.relative_to(repo)) == target]
    if by_relpath:
        return by_relpath[0]

    by_name = [p for p in all_projects if p.name == Path(target).stem]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        options = ", ".join(str(p.path.relative_to(repo)) for p in by_name)
        raise ProjectNotFoundError(
            f"Multiple projects named '{name}' — specify the full relative path: {options}"
        )
    raise ProjectNotFoundError(f"No project named '{name}' found. Run 'dam list' to see available projects.")
