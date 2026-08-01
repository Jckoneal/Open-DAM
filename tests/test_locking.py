from concurrent.futures import ThreadPoolExecutor

import pytest

from collaborate import locking
from collaborate.errors import LockHeldError


def test_claim_then_second_claim_fails(alice, bob):
    project = alice / "MyProject.prproj"
    lock = locking.claim_lock(alice, project)
    assert lock.status == "locked"
    assert lock.locked_by["user"] == "alice@example.com"

    with pytest.raises(LockHeldError):
        locking.claim_lock(bob, bob / "MyProject.prproj")


def test_release_then_reclaim(alice, bob):
    project_a = alice / "MyProject.prproj"
    locking.claim_lock(alice, project_a)
    identity = locking.current_identity(alice)
    locking.release_lock(alice, project_a, identity)

    from collaborate import git_ops
    git_ops.add(alice, [str(locking.lock_path_for(project_a))])
    git_ops.commit(alice, "release")
    git_ops.push(alice)

    lock = locking.claim_lock(bob, bob / "MyProject.prproj")
    assert lock.locked_by["user"] == "bob@example.com"


def test_concurrent_claims_exactly_one_wins(alice, bob):
    def try_claim(repo):
        try:
            return ("won", locking.claim_lock(repo, repo / "MyProject.prproj"))
        except LockHeldError as e:
            return ("lost", e)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_claim, [alice, bob]))

    outcomes = [r[0] for r in results]
    assert outcomes.count("won") == 1
    assert outcomes.count("lost") == 1
