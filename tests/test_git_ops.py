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


def test_is_empty_commit_noop_on_a_clean_tree(alice):
    result = git_ops.commit(alice, "nothing changed")
    assert not result.ok
    assert git_ops.is_empty_commit_noop(result)


def test_is_empty_commit_noop_with_an_unrelated_untracked_file(alice):
    """Regression: reported in the field as checkin's "Push & Keep Lock"
    raising a blank "commit failed:" error. Git phrases "nothing to commit"
    differently when unrelated untracked files exist elsewhere in the repo
    ("nothing added to commit but untracked files present") — realistic in
    an actively-used library — and that phrasing doesn't contain the literal
    substring "nothing to commit", so a narrower check misclassified this
    exact case as a real failure."""
    (alice / "some_other_stray_file.txt").write_text("unrelated\n")
    result = git_ops.commit(alice, "nothing changed")
    assert not result.ok
    assert "nothing to commit" not in result.stdout.lower()
    assert git_ops.is_empty_commit_noop(result)


def test_is_empty_commit_noop_with_unrelated_modified_tracked_file(alice, bob):
    """The third git phrasing: some other tracked file has unstaged
    modifications, but nothing was staged for this commit at all
    ("no changes added to commit")."""
    (bob / "MyProject.prproj").write_text("bob's own edit, never staged\n")
    result = git_ops.commit(bob, "nothing changed")
    assert not result.ok
    assert "nothing to commit" not in result.stdout.lower()
    assert git_ops.is_empty_commit_noop(result)


def test_is_empty_commit_noop_false_for_a_real_failure(alice):
    # a genuinely broken repo state, not a benign empty commit
    fake_result = git_ops.GitResult(ok=False, stdout="", stderr="fatal: bad object HEAD", returncode=128)
    assert not git_ops.is_empty_commit_noop(fake_result)
