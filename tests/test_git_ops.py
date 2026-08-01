from collaborate import git_ops


def test_fetch_and_pull(alice):
    result = git_ops.fetch(alice)
    assert result.ok
    result = git_ops.pull_ff_only(alice)
    assert result.ok


def test_is_dirty(alice):
    assert not git_ops.is_dirty(alice)
    (alice / "MyProject.prproj").write_text("changed\n")
    assert git_ops.is_dirty(alice, [str(alice / "MyProject.prproj")])


def test_push_rejected_detection(alice, bob):
    (alice / "MyProject.prproj").write_text("alice edit\n")
    git_ops.add(alice, ["MyProject.prproj"])
    git_ops.commit(alice, "alice edit")
    git_ops.push(alice)

    (bob / "MyProject.prproj").write_text("bob edit\n")
    git_ops.add(bob, ["MyProject.prproj"])
    git_ops.commit(bob, "bob edit")
    result = git_ops.push(bob)

    assert not result.ok
    assert git_ops.is_push_rejected(result)
