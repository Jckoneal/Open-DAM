import subprocess

from collaborate import git_ops
from collaborate.errors import RemoteUnreachableError


def test_fetch_and_pull(alice):
    result = git_ops.fetch(alice)
    assert result.ok
    result = git_ops.pull_ff_only(alice)
    assert result.ok


def test_network_call_timeout_raises_remote_unreachable(alice, monkeypatch):
    """A fetch/pull/push stuck on an unanswerable SSH host-key/credential
    prompt (nothing running it has a terminal to answer in — the menu bar
    app's periodic sync least of all) used to hang forever, freezing
    whatever thread called it. run_git's network timeout must turn that
    into a normal, catchable OpenDamError instead."""
    def fake_run(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="git fetch", timeout=git_ops.NETWORK_TIMEOUT_SECONDS)

    monkeypatch.setattr(git_ops.subprocess, "run", fake_run)

    try:
        git_ops.fetch(alice)
        assert False, "expected RemoteUnreachableError"
    except RemoteUnreachableError:
        pass


def test_local_only_calls_get_no_network_env_or_timeout(alice, monkeypatch):
    """config/rev-parse/commit/etc. never touch a remote — they must not
    get the network env override (which disables SSH host-key/credential
    prompting; fine for an unattended fetch, wrong for e.g. a legitimate
    first-time `collab clone` prompt a human is present to answer) or a
    timeout that could cut off a slow local operation on a huge repo."""
    seen = {}

    def fake_run(args, cwd, capture_output, text, env, timeout):
        seen["env"] = env
        seen["timeout"] = timeout
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(git_ops.subprocess, "run", fake_run)

    git_ops.run_git(["status"], alice)

    assert seen["env"] is None
    assert seen["timeout"] is None


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
