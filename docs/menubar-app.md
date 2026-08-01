# The Collaborate menu bar app

A small icon in your Mac's top bar (next to the clock, wifi icon, etc.) showing
whatever you have checked out front and center, everyone else's status below
it, and checkout/check-in/release/new-project one click away — no terminal
needed for day-to-day use once it's set up.

```
🎬  ▾                                (menu bar icon — plain template glyph;
 ├ CHECKED OUT BY YOU                 color only ever appears in the menu)
 ├ ● Ep01_RoughCut — 2h 14m
 │   ├ Check In…
 │   └ Release
 ├ ─────────────
 ├ Projects
 ├ ○ Ep02_Assembly (1)                ← available, 1 open note
 ├ 🔒 Ep03_Color — sam · 4h
 ├ 🔒 Ep04_VFX — dana · 26h ⚠         ← stale (past stale_lock_hours)
 ├ ─────────────
 ├ New Project…                ⌘N
 ├ Sync Now                    ⌘R
 ├ Settings…                   ⌘,
 └ Quit Collaborate            ⌘Q
```

This layout follows the "focus card" direction from the project's Curate
Menubar Wireframes design: whatever you're actively holding is never buried in
a flat list — it's its own section at the top. Per that design's own
annotation, the status-bar icon itself is a plain macOS template image and
never changes color or shape for any state (idle, holding a lock, syncing) —
only the menu contents and a transient title-text flash (e.g. "✓ Ep02
free") do. That's a deliberate, HIG-correct choice, not a missing feature.

It reuses the exact same lock/git/ticket logic as the `collab` CLI (they share
`collaborate.locking`, `collaborate.git_ops`, `collaborate.tickets` directly, in-process —
unlike the Premiere CEP panel, which has to shell out to `collab` because
JavaScript can't import Python). The one thing it can't do that the CLI can:
save-and-close Premiere for you, since that needs Premiere's own scripting
hooks — see [the Premiere panel](premiere-panel.md) for that piece if you use it.

## Requirements

macOS. Your Mac's login `git` identity configured, and the project library
already cloned + `collab init` run once (see the
[Getting Started guide](getting-started.md)).

## Install

```bash
pip install -e ".[menubar]"     # from a clone of this (Collaborate) repository
collab menubar
```

The first launch asks for your project library folder (the one from
`collab clone`) in a small dialog, then the icon appears in your menu bar.

**To start it automatically at login:**

```bash
./scripts/install-menubar-launchagent.sh
```

This installs a LaunchAgent that runs `collab menubar` at login. Logs go to
`~/Library/Logs/collaborate-menubar.log`. To remove it later:

```bash
launchctl unload ~/Library/LaunchAgents/com.collaborate.menubar.plist
rm ~/Library/LaunchAgents/com.collaborate.menubar.plist
```

## Using it

**Checked out by you** — surfaces at the top whenever you hold a lock, with
elapsed time and a stale warning (⚠) if you've held it past
`stale_lock_hours`. Click for a submenu:
- **Check In…** — asks whether you've saved and closed in Premiere, then
  a small sheet to optionally describe what changed, with two ways to
  finish: **Push** (commits, pushes, releases the lock) or **Push & Keep
  Lock** (same, but you keep working).
- **Release** — frees the project without saving a new version (confirms first).

**Projects** — everything else, available and locked-by-others together:
- **○ available** — click to check out. Claims the lock and opens the project
  in Premiere, same as `collab checkout`.
- **🔒 locked by someone else** — click it anyway: nothing on your machine
  changes, but you can **Add Note…** to leave them a note (the same tickets
  `collab ticket add` writes) without waiting for the lock.
- A number in parentheses is that project's open note/ticket count. `⚠` after
  a locked row means it's been held past `stale_lock_hours` — ask around, or
  an admin can `collab release <project> --force` from the Terminal.

**Elsewhere in the menu:**
- **New Project…** (⌘N) — only works if a `template_path` is configured
  (`collab config set template_path <path>`); creates from it, commits,
  pushes, and checks it out to you in one step. Without a template configured,
  it tells you to use `collab new <name>` in Terminal instead — that flow
  needs to wait for you to manually save a new project in Premiere, which
  doesn't fit a single menu click.
- **Sync Now** (⌘R) — refresh immediately instead of waiting for the
  automatic 30-second cycle.
- **Settings…** (⌘,) — change which project library folder this machine points at.
- The list also flashes "✓ *Project* free" for a couple of seconds when
  someone else's lock is released between refreshes — even if you didn't
  cause it — so you don't have to keep checking back.

## How it works (for maintainers)

`src/collaborate/menubar_model.py` holds all the actual logic — settings storage,
syncing with the remote, grouping/elapsed-time/staleness, and diffing two
refreshes to detect projects freed by someone else — as plain functions with
no `rumps` import, so it's unit-testable without the `menubar` extra installed
(see `tests/test_menubar_model.py`). `src/collaborate/menubar_app.py` is the
rumps-specific layer on top: it renders that model as a menu, wires up
clicks, and runs git/lock work on a background thread (via
`AppHelper.callAfter` to marshal results back to the main thread — AppKit
enforces that all UI updates, including alerts and menu rebuilding, happen on
the main thread only) so a slow git operation never freezes the icon.

The status-bar icon (`src/collaborate/assets/menubar-icon*.png`) is a real
macOS template image sourced from the project's Claude Design workspace, not
an emoji — template images get free light/dark-menu-bar and click-highlight
adaptation from AppKit that a plain title glyph doesn't.

Known limitations:

- **macOS only**, same as the Premiere launcher.
- **Doesn't drive Premiere itself** — no save/close automation. Use the
  [Premiere panel](premiere-panel.md) if you want that; the two aren't
  mutually exclusive.
- **New Project… needs a configured template.** Without one, creating a
  project still needs the Terminal (`collab new`), which can walk you through
  the manual-save flow interactively in a way a single menu click can't.
- No OS notification center integration — it needs a real `.app` bundle
  identity (`CFBundleIdentifier`) that a bare script run via the `collab`
  console command structurally can't have, so success/freed-project feedback
  shows as a title-text flash instead.
- First-run, "Settings…", "New Project…", and "Add Note…" all use a blocking
  system dialog — needs a real interactive login session (as any menu bar app
  does), so none of it can be driven or verified from a headless script.
