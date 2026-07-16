# Design notes

## Why not "each project on its own branch"?

The obvious-looking idea is: give each Premiere project its own branch, and have
editors `git checkout` that branch. It doesn't actually solve the problem.

Git branches are local pointers, not locks. Two people can independently be on the
same branch on two different machines and both open the same `.prproj` at the same
time — a branch doesn't stop that. The thing that actually needs to be exclusive is
*who is currently editing this file*, not *which history line it lives on*. Branches
would also add merge overhead (checking a project back into `main` becomes a binary
merge — the exact problem we're trying to avoid) without adding any exclusivity
guarantee.

So Open-DAM uses a single shared `main` branch. Every project's `.prproj` and its
lock file live there. The lock file — not the branch — is what provides mutual
exclusion.

## Lock file, not a lock server

The lock is a small JSON file committed into the repo, next to the project it
guards (`<Project>.prproj.lock.json`), rather than an external database or lock
server. This means:

- It works with any plain Git remote — no dependency on a host supporting an LFS
  file-locking API or running a side service.
- Locking different projects never contends with each other on push, since each
  project's lock is its own file.
- The lock's history is just Git history — `git log --follow` on a lock file is a
  full audit trail of who checked a project in and out, and when, with no separate
  logging system.

On release, the file is rewritten to an explicit `unlocked` sentinel rather than
deleted — deleting is itself a mutation that can race ambiguously (did it get
deleted because it was released, or did I never see it exist?).

## The claim race

Git has no server-side locking primitive, so acquiring a lock is an optimistic
pull → check → claim → push → verify loop (`opendam.locking.claim_lock`):

1. Fetch and fast-forward pull.
2. Read the lock file. Abort if someone else holds it.
3. Write a new lock (my identity, a fresh UUID as `lock_id`, a timestamp), commit,
   and push.
4. If the push is rejected (someone else pushed first), re-fetch and check who won.
   If it was genuinely someone else's claim, abort and report them. If the lock
   turns out to still be free (a benign unrelated push), retry.
5. If the push succeeds, re-pull and confirm the lock file's `lock_id` matches the
   one I just wrote — this disambiguates "my claim landed" from "a claim with the
   same nominal state landed a moment before mine, and mine is about to fail."

Retries are bounded (5 attempts, ~1.5s backoff) before giving up with a clear
"remote is contended" error, rather than retrying forever.

One subtlety that only shows up under real concurrency: `git pull --ff-only` fails
on topological divergence — a local commit that never got pushed, plus a remote
that has since moved — even when there's no actual content conflict. A failed claim
attempt's own commit is disposable (it only ever touches the lock file), so on
retry it's explicitly unstaged and discarded (`git_ops.discard_path`) before
re-pulling, rather than trying to merge or rebase it away.

Check-in and release use the same push-retry helper, but rebase instead of discard
on rejection (`git pull --rebase`) — a check-in's commit is real work, not
disposable, and the lock invariant guarantees no one else touched that project's
files in the meantime, so the rebase can only ever replay cleanly.

## Detecting "done editing"

Premiere has no reliable scriptable "on close" hook without ExtendScript/UXP, and
the process staying alive doesn't mean any particular project is still open in it.
Rather than polling for the process to exit, `dam checkin` just asks: "have you
saved and closed the project?" A best-effort `is_running()` check can annotate that
prompt with a warning, but it never blocks or auto-triggers anything.

## Stale locks are never auto-reclaimed

If someone force-quits without checking in, their lock just sits there. `dam
status`/`dam list` surface its age, but recovering it is always a deliberate
`--force` action by a human, not an automatic timeout — with a confirmation prompt
and an audit record (`forced_by`) written into the resulting lock file. A small team
doesn't need real RBAC for this; the confirmation-plus-audit-trail is deliberately
the whole mechanism for v1.
