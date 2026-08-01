# Open-DAM

A Git-based checkout manager for Adobe Premiere Pro projects with local media storage so teams can work together without spending thousands on a Digital Asset Manager.

Premiere Pro project files (`.prproj`) can't be merged the way text files can. If two
editors modify the same project on different machines, there's no reconciling the
conflict — someone's work gets lost. Open-DAM adds a Perforce/Git-LFS-lock-style
workflow on top of a plain Git repo: before editing a project you "check it out"
through the `dam` CLI, which pulls the latest version, claims an exclusive lock so
nobody else can also check it out, and launches Premiere Pro directly on the file.
When you're done, "check in" commits, pushes, and releases the lock for the next
person.

Raw footage/audio is **not** stored in Git. Every editor's machine has the same
source media pre-populated at the same relative path, so Premiere's relative media
links resolve identically everywhere — Git only ever tracks the small `.prproj`
files and their lock metadata.

> **New to this — or setting it up for a team of editors?** Read the
> **[Getting Started guide](docs/getting-started.md)** instead of this page. It
> assumes no Git or Terminal experience, walks through joining an existing team
> library step by step, and has a section for the team lead creating one from
> scratch. This README is the technical reference.

## How locking works

Each project has a sibling lock file committed alongside it on `main`:

```
Projects/MyShow_Ep01.prproj
Projects/MyShow_Ep01.prproj.lock.json
```

`dam checkout` runs an optimistic pull → check → claim → push → verify loop: it
pulls the latest lock state, refuses if someone else already holds it, otherwise
writes a new lock (your identity, a timestamp, a UUID) and pushes. If two people
race for the same project, exactly one push wins — the loser re-pulls, sees who won,
and gets a clear rejection. Locking different projects never contends with each
other, since each project's lock lives in its own file.

There is no separate lock server and no per-project/per-user branch — everything
lives on one shared `main` branch, and the lock file *is* the mutex. See
[docs/design.md](docs/design.md) if you want the full rationale, including why
branches alone don't solve this problem.

## Installation

Requires Python 3.9+ and Git.

```bash
pip install -e .
```

This installs the `dam` command (via the `[project.scripts]` entry point in
`pyproject.toml`).

## Quickstart

**First-time setup for a new team member**, once the DAM repo already exists on a
remote:

```bash
dam clone git@github.com:your-org/your-premiere-projects.git --dir ~/dam/your-project
cd ~/dam/your-project
dam init      # sets git identity, local media root, discovers your Premiere install
dam doctor    # confirms everything checks out
```

**Starting a brand-new project:**

```bash
dam new MyShow_Ep02
```

If a `template_path` is configured (set during `dam init`, or via
`dam config set template_path <path>`), it's copied in as the starting point. Otherwise
`dam new` launches a blank Premiere and asks you to save your new project at the path
it gives you. Either way, it commits + pushes the new project and immediately claims
the lock for you (Premiere doesn't have a scriptable "create a new project with these
settings" hook, so this is as far outside-in automation can go — you still drive the
actual project creation inside Premiere's own UI when there's no template).

**Bringing an existing `.prproj` under management:**

```bash
dam import ~/Desktop/SomeProject.prproj          # copies it in, keeps the original
dam import ~/Desktop/SomeProject.prproj --move   # copies it in, deletes the original
dam import ~/Desktop/SomeProject.prproj MyShow_Ep03 --checkout   # rename + claim the lock
```

**Day-to-day workflow:**

```bash
dam list                    # see all projects and their lock status
dam checkout MyShow_Ep01     # pull latest, claim the lock, launch Premiere
# ... edit in Premiere, save, close ...
dam checkin MyShow_Ep01      # commit, push, release the lock
```

**If you need to step away without finishing:**

```bash
dam checkin MyShow_Ep01 --keep-lock   # push your progress, keep the lock
dam release MyShow_Ep01               # or give up the lock with no commit
```

**Leaving notes / tickets** (no checkout needed — anyone can flag work on any
project; open tickets are shown automatically at checkout):

```bash
dam ticket add MyShow_Ep01 "Fix audio sync at 02:14"
dam ticket list MyShow_Ep01
dam ticket done MyShow_Ep01 a3f2
dam checkin MyShow_Ep01 --note "rough cut done, needs color"   # note + checkin in one commit
```

Tickets are stored like locks are: small JSON files committed in the repo, one
file per ticket (`Ep01.prproj.tickets/<id>.json`), so concurrent adds from
different editors can never conflict.

**Recovering a stale lock** (someone force-quit without checking in — never done
automatically, always a deliberate human action):

```bash
dam status MyShow_Ep01       # check how old the lock is and who holds it
dam release MyShow_Ep01 --force
```

## Command reference

| Command | Purpose |
|---|---|
| `dam init` | Interactive wizard: git identity, media root, Premiere path, template → `.damconfig.yaml` |
| `dam clone <remote-url>` | Clone the DAM repo and set up local config |
| `dam new <name>` | Create a new project (from template, or via a blank Premiere launch), register it, claim the lock (`--no-launch`) |
| `dam import <source> [name]` | Register an existing `.prproj` (`--move`, `--checkout`) |
| `dam list` | Table of all projects: name, lock status, holder, since |
| `dam status [<project>]` | Detailed lock + local working-tree status |
| `dam checkout <project>` | Pull, claim the lock, launch Premiere (`--no-launch`, `--force`) |
| `dam checkin <project>` | Commit, push, release the lock (`-m`, `--force-checkin`, `--keep-lock`, `--note "text"`) |
| `dam release <project>` | Release the lock without committing (`--force`, `--discard-local`) |
| `dam ticket add <project> "text"` | Attach a note/ticket to a project — no lock needed |
| `dam ticket list <project>` | Show a project's tickets (`--open` to hide done ones) |
| `dam ticket done <project> <id>` | Mark a ticket done (id prefix from `ticket list`) |
| `dam config get/set` | Read/write `.damconfig.yaml` values |
| `dam doctor` | Diagnostics: git, remote, Premiere path, media root |

## Configuration

Each clone has its own `.damconfig.yaml` at the repo root (gitignored — it's
per-machine, not shared history):

```yaml
schema_version: 1
remote: git@github.com:your-org/your-premiere-projects.git
media_root: /Volumes/EDIT_SSD/ProjectMedia
premiere:
  app_path: "/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app"
stale_lock_hours: 24
template_path: /Volumes/EDIT_SSD/Templates/HouseStyle.prproj
```

Git identity (`user.name`/`user.email`) is read from your existing global Git
config, not duplicated here — it's what locks are attributed to.

## Platform support

macOS is fully supported. Windows launching (`WindowsLauncher` in
`src/opendam/launcher.py`) is scaffolded but unvalidated — it needs testing on real
Windows hardware before relying on it.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Tests spin up real local bare Git repositories in `tmp_path` and exercise the actual
`git` binary (no mocking) — including a concurrency test that races two real
`dam checkout` calls against the same repo to verify exactly one wins.

## License

MIT — see [LICENSE](LICENSE).
