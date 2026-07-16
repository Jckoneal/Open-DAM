"""Lock file data model and the race-safe claim/verify loop.

Each project has a single sibling lock file (`<Project>.prproj.lock.json`)
committed on `main`. Locking different projects touches different files, so
unrelated checkouts never contend with each other on push — the only race
this module has to resolve is two people claiming the *same* project at
close to the same time.
"""

from __future__ import annotations

import json
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from opendam import git_ops
from opendam.errors import GitCommandError, LockHeldError, StaleLockRaceError

SCHEMA_VERSION = 1
MAX_CLAIM_RETRIES = 5
RETRY_BACKOFF_SECONDS = 1.5


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_path_for(project_file: Path) -> Path:
    return project_file.with_suffix(project_file.suffix + ".lock.json")


@dataclass
class Lock:
    schema_version: int
    status: str  # "locked" | "unlocked"
    project_file: str
    locked_by: Optional[dict] = None
    locked_at: Optional[str] = None
    branch: Optional[str] = None
    lock_id: Optional[str] = None
    last_released_by: Optional[dict] = None
    last_released_at: Optional[str] = None
    forced_by: Optional[dict] = None

    @classmethod
    def unlocked_default(cls, project_file: str) -> "Lock":
        return cls(schema_version=SCHEMA_VERSION, status="unlocked", project_file=project_file)

    @classmethod
    def load(cls, path: Path) -> "Lock":
        if not path.exists():
            raise FileNotFoundError(path)
        data = json.loads(path.read_text())
        return cls(**data)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")

    def is_locked(self) -> bool:
        return self.status == "locked"

    def is_held_by(self, user_email: str) -> bool:
        return self.is_locked() and bool(self.locked_by) and self.locked_by.get("user") == user_email


def current_identity(repo: Path) -> dict:
    email = git_ops.get_config(repo, "user.email") or "unknown@local"
    name = git_ops.get_config(repo, "user.name") or email
    return {"user": email, "git_name": name, "hostname": socket.gethostname()}


def claim_lock(repo: Path, project_file: Path, remote: str = "origin", branch: Optional[str] = None) -> Lock:
    """Optimistic pull -> check -> claim -> push -> verify loop.

    Returns the winning Lock on success. Raises LockHeldError if someone
    else holds (or wins the race for) the lock, or StaleLockRaceError if the
    remote stays contended past MAX_CLAIM_RETRIES.
    """
    branch = branch or git_ops.current_branch(repo)
    identity = current_identity(repo)
    lpath = lock_path_for(project_file)
    my_lock_id = str(uuid.uuid4())
    made_commit = False

    for attempt in range(MAX_CLAIM_RETRIES):
        if made_commit:
            # Our previous claim attempt never landed — it's the topmost
            # local commit and touched only the lock file, so undoing it is
            # always safe (never discards anyone else's work).
            git_ops.reset_soft(repo, "HEAD~1")
            git_ops.discard_path(repo, str(lpath))
            made_commit = False

        git_ops.fetch(repo, remote)
        git_ops.pull_ff_only(repo, remote, branch)

        existing = Lock.load(lpath) if lpath.exists() else Lock.unlocked_default(_rel(repo, project_file))
        if existing.is_locked() and not existing.is_held_by(identity["user"]):
            raise LockHeldError(project_file.name, existing)
        if existing.is_locked() and existing.is_held_by(identity["user"]):
            # Crash-recovery: I already hold it, nothing new to claim.
            return existing

        new_lock = Lock(
            schema_version=SCHEMA_VERSION,
            status="locked",
            project_file=_rel(repo, project_file),
            locked_by=identity,
            locked_at=utcnow_iso(),
            branch=branch,
            lock_id=my_lock_id,
        )
        new_lock.save(lpath)
        git_ops.add(repo, [str(lpath)])
        git_ops.commit(repo, f"lock: checkout {project_file.stem} by {identity['user']}")
        made_commit = True

        push_result = git_ops.push(repo, remote, branch)
        if push_result.ok:
            git_ops.fetch(repo, remote)
            git_ops.pull_ff_only(repo, remote, branch)
            landed = Lock.load(lpath)
            if landed.lock_id == my_lock_id:
                return landed
            # Someone else's push landed in between fetch and push somehow — retry.
        elif not git_ops.is_push_rejected(push_result):
            raise GitCommandError(["push", remote, branch], push_result.returncode, push_result.stderr)

        time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

    raise StaleLockRaceError(
        f"Could not acquire lock for {project_file.name} after {MAX_CLAIM_RETRIES} attempts "
        "— the remote is contended, try again shortly."
    )


def release_lock(
    repo: Path,
    project_file: Path,
    identity: dict,
    force: bool = False,
    forced_by: Optional[dict] = None,
) -> Lock:
    lpath = lock_path_for(project_file)
    existing = Lock.load(lpath) if lpath.exists() else Lock.unlocked_default(_rel(repo, project_file))

    if existing.is_locked() and not existing.is_held_by(identity["user"]) and not force:
        raise LockHeldError(project_file.name, existing)

    released = Lock(
        schema_version=SCHEMA_VERSION,
        status="unlocked",
        project_file=_rel(repo, project_file),
        last_released_by=identity,
        last_released_at=utcnow_iso(),
        forced_by=forced_by if force else None,
    )
    released.save(lpath)
    return released


def _rel(repo: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)
