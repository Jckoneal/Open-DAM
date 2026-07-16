"""Thin, explicit wrapper over git subprocess calls.

Raw subprocess (not GitPython) is used deliberately so callers can branch on
precise git exit/stderr semantics (non-fast-forward push vs. auth failure vs.
offline) rather than an abstraction library's interpretation of them.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from opendam.errors import GitCommandError, RemoteUnreachableError

NETWORK_ERROR_MARKERS = (
    "could not resolve host",
    "unable to access",
    "connection refused",
    "network is unreachable",
    "operation timed out",
)

NON_FAST_FORWARD_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "rejected",
)


@dataclass
class GitResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int


def run_git(args: list[str], cwd: Path, check: bool = True) -> GitResult:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    result = GitResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
    )
    if check and not result.ok:
        _raise_git_error(args, result)
    return result


def _raise_git_error(args: list[str], result: GitResult) -> None:
    lowered = result.stderr.lower()
    if any(marker in lowered for marker in NETWORK_ERROR_MARKERS):
        raise RemoteUnreachableError(result.stderr.strip())
    raise GitCommandError(args, result.returncode, result.stderr)


def _is_unborn_remote_branch(result: GitResult) -> bool:
    """True when a pull failed only because the remote branch doesn't exist
    yet — a brand-new remote nobody has pushed to. Nothing to pull; the
    first push will create the branch."""
    return "couldn't find remote ref" in result.stderr.lower()


def fetch(repo: Path, remote: str = "origin") -> GitResult:
    return run_git(["fetch", remote], repo)


def pull_ff_only(repo: Path, remote: str = "origin", branch: str | None = None) -> GitResult:
    branch = branch or current_branch(repo)
    args = ["pull", "--ff-only", remote, branch]
    result = run_git(args, repo, check=False)
    if not result.ok and not _is_unborn_remote_branch(result):
        _raise_git_error(args, result)
    return result


def pull_rebase(repo: Path, remote: str = "origin", branch: str | None = None) -> GitResult:
    """Rebase our own not-yet-pushed commit onto a remote that advanced with
    unrelated commits. Safe here because the lock invariant guarantees only
    the lock holder touches a given project's files, so this can only
    replay cleanly — never a real content conflict."""
    branch = branch or current_branch(repo)
    return run_git(["pull", "--rebase", remote, branch], repo, check=False)


def reset_soft(repo: Path, ref: str = "HEAD~1") -> GitResult:
    return run_git(["reset", "--soft", ref], repo)


def discard_path(repo: Path, path: str) -> None:
    """Discard any local commit/index/working-tree state for a single path,
    restoring it to whatever HEAD has (or removing it if HEAD has no such
    path). `reset --soft` alone leaves the path staged in the index even
    after the commit that added it is undone, so it must be explicitly
    unstaged too or a later pull sees a phantom local change."""
    run_git(["reset", "HEAD", "--", path], repo, check=False)
    result = run_git(["checkout", "HEAD", "--", path], repo, check=False)
    if not result.ok and Path(path).exists():
        Path(path).unlink()


def push(repo: Path, remote: str = "origin", branch: str | None = None) -> GitResult:
    """Push without raising on non-fast-forward rejection — callers need to
    distinguish that from a hard failure to drive the retry loop."""
    branch = branch or current_branch(repo)
    return run_git(["push", "-u", remote, branch], repo, check=False)


def is_push_rejected(result: GitResult) -> bool:
    lowered = result.stderr.lower()
    return not result.ok and any(marker in lowered for marker in NON_FAST_FORWARD_MARKERS)


def add(repo: Path, paths: list[str]) -> GitResult:
    return run_git(["add", *paths], repo)


def commit(repo: Path, message: str, allow_empty: bool = False) -> GitResult:
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    return run_git(args, repo, check=False)


def status_porcelain(repo: Path, paths: list[str] | None = None) -> list[str]:
    args = ["status", "--porcelain"]
    if paths:
        args += ["--", *paths]
    result = run_git(args, repo)
    return [line for line in result.stdout.splitlines() if line.strip()]


def is_dirty(repo: Path, paths: list[str] | None = None) -> bool:
    return len(status_porcelain(repo, paths)) > 0


def clone(remote_url: str, dest: Path) -> GitResult:
    return run_git(["clone", remote_url, str(dest)], dest.parent)


def get_config(repo: Path, key: str) -> str | None:
    result = run_git(["config", "--get", key], repo, check=False)
    return result.stdout.strip() or None


def current_branch(repo: Path) -> str:
    """Name of the checked-out branch. `symbolic-ref` (not `rev-parse`)
    because it also works on an unborn branch — a fresh clone of an empty
    remote, where no commit exists yet."""
    result = run_git(["symbolic-ref", "--short", "HEAD"], repo, check=False)
    if result.ok:
        return result.stdout.strip()
    return "main"  # detached HEAD — shouldn't happen in a DAM repo, but don't crash
