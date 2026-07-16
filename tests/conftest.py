import subprocess
from pathlib import Path

import pytest


def _run(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_user_clone(bare: Path, dest: Path, email: str, name: str) -> Path:
    subprocess.run(["git", "clone", str(bare), str(dest)], check=True, capture_output=True, text=True)
    _run(["config", "user.email", email], dest)
    _run(["config", "user.name", name], dest)
    return dest


@pytest.fixture
def bare_repo(tmp_path):
    bare = tmp_path / "origin.git"
    _run(["init", "--bare", "-b", "main", str(bare)], tmp_path)

    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(bare), str(seed)], check=True, capture_output=True, text=True)
    _run(["config", "user.email", "seed@local"], seed)
    _run(["config", "user.name", "Seed"], seed)
    (seed / "MyProject.prproj").write_text("fake premiere project contents\n")
    _run(["add", "MyProject.prproj"], seed)
    _run(["commit", "-m", "seed project"], seed)
    _run(["push", "origin", "main"], seed)
    return bare


@pytest.fixture
def alice(bare_repo, tmp_path):
    return _init_user_clone(bare_repo, tmp_path / "alice", "alice@example.com", "Alice")


@pytest.fixture
def empty_remote_clone(tmp_path):
    """A clone of a brand-new remote that has never been pushed to — the
    state right after creating an empty repo on GitHub and cloning it."""
    bare = tmp_path / "empty_origin.git"
    _run(["init", "--bare", "-b", "main", str(bare)], tmp_path)
    return _init_user_clone(bare, tmp_path / "fresh", "alice@example.com", "Alice")


@pytest.fixture
def bob(bare_repo, tmp_path):
    return _init_user_clone(bare_repo, tmp_path / "bob", "bob@example.com", "Bob")
