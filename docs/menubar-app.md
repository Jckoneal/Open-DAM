# The Open-DAM menu bar app

A small icon in your Mac's top bar (next to the clock, wifi icon, etc.) showing
every project's status, with checkout/check-in/release one click away — no
terminal needed for day-to-day use once it's set up.

```
🎬  ▾                       (menu bar, next to the clock)
 ├ ○ Ep01                    ← available, click to check out
 ├ ● Ep02                    ← yours: submenu → Check In / Release
 ├ 🔒 Ep03 — dana@example.com
 ├ ○ Ep04 (2)                ← available, 2 open tickets
 ├ ─────────────
 ├ Refresh Now
 ├ Change Library Folder…
 └ Quit
```

It reuses the exact same lock/git/ticket logic as the `dam` CLI (they share
`opendam.locking`, `opendam.git_ops`, `opendam.tickets` directly, in-process —
unlike the Premiere CEP panel, which has to shell out to `dam` because
JavaScript can't import Python). The one thing it can't do that the CLI can:
save-and-close Premiere for you, since that needs Premiere's own scripting
hooks — see [the Premiere panel](premiere-panel.md) for that piece if you use it.

## Requirements

macOS. Your Mac's login `git` identity configured, and the project library
already cloned + `dam init` run once (see the
[Getting Started guide](getting-started.md)).

## Install

```bash
pip install -e ".[menubar]"     # from a clone of this (Open-DAM) repository
dam menubar
```

The first launch asks for your project library folder (the one from
`dam clone`) in a small dialog, then the icon appears in your menu bar.

**To start it automatically at login:**

```bash
./scripts/install-menubar-launchagent.sh
```

This installs a LaunchAgent that runs `dam menubar` at login. Logs go to
`~/Library/Logs/open-dam-menubar.log`. To remove it later:

```bash
launchctl unload ~/Library/LaunchAgents/com.opendam.menubar.plist
rm ~/Library/LaunchAgents/com.opendam.menubar.plist
```

## Using it

- **○ available** — click to check out. Claims the lock and opens the project
  in Premiere, same as `dam checkout`.
- **● yours** — click for a submenu: **Check In** (asks whether you've saved
  and closed in Premiere, then commits + pushes + releases) or **Release**
  (frees it without saving a new version — asks to confirm).
- **🔒 locked by someone else** — informational only, not clickable.
- A number in parentheses is that project's open ticket count.
- The list refreshes automatically every 30 seconds, and re-syncs with the
  team library every time (yours or a manual **Refresh Now**).
- **Change Library Folder…** if you ever need to point it at a different clone.

## How it works (for maintainers)

`src/opendam/menubar_model.py` holds all the actual logic — settings storage,
syncing with the remote, and building the list of projects with their status
— as plain functions with no `rumps` import, so it's unit-testable without the
`menubar` extra installed (see `tests/test_menubar_model.py`). `src/opendam/menubar_app.py`
is a thin layer on top that renders that model as a `rumps.App` menu and wires
up clicks; actions run on a background thread so a slow git operation never
freezes the icon.

Known limitations:

- **macOS only**, same as the Premiere launcher.
- **Doesn't drive Premiere itself** — no save/close automation. Use the
  [Premiere panel](premiere-panel.md) if you want that; the two aren't
  mutually exclusive.
- No **New…**/**Import** actions yet (CLI-only for now); no ticket viewing UI
  beyond the count badge.
- First-run and "change folder" use a blocking system dialog — needs a real
  interactive login session (as any menu bar app does), so it can't be
  driven or verified from a headless script.
