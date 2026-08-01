# The Collaborate Premiere Pro panel

A panel that lives inside Premiere Pro (**Window → Extensions → Collaborate**) so
editors can check projects out and in without touching the Terminal after
one-time setup.

Because the panel runs inside Premiere, check-in can do the one thing the CLI
never could: **save and close the project automatically** before committing.
Click *Check In* and the panel saves the open project, closes it, and pushes it
to the team library in one step.

## What it looks like

- Every project in the library, listed with a colored badge: **available**,
  **yours**, or **locked** (with who has it).
- **Checkout** on available projects — claims the lock and opens the project in
  Premiere.
- **Check In** / **Release** on projects you hold. Check In saves + closes +
  pushes; Release asks for a second confirming click, then frees the project
  without saving a new version.
- **New…** creates a project from your team's template, already checked out and
  open. (Requires a configured `template_path` — the panel can't drive
  Premiere's own New Project dialog.)
- The list refreshes automatically every 30 seconds, and syncs with the team
  library on every refresh.

## Requirements

- macOS with Premiere Pro 2022 or newer.
- The `collab` CLI installed and the team library cloned + `collab init` run
  (see the [Getting Started guide](getting-started.md), Part 1).

## Install

From a clone of this (Collaborate) repository:

```bash
./scripts/install-premiere-panel.sh
```

Then restart Premiere Pro and open **Window → Extensions → Collaborate**.

The script copies the panel into `~/Library/Application Support/Adobe/CEP/extensions/`
and enables `PlayerDebugMode` — the panel is unsigned, and Premiere refuses to
load unsigned panels without that flag. (Signing with a ZXP certificate would
remove that requirement; it's on the roadmap, not done yet.)

## First-run setup inside the panel

The first time it opens, the panel asks for two paths:

- **Project library folder** — where you cloned the team repo
  (e.g. `/Users/you/Premiere-Projects`).
- **Path to the collab command** — usually auto-detected; only fill it in if the
  panel says it can't find `collab`. (`command -v collab` in Terminal prints it.)

Settings are per-machine, stored by the panel itself, and reachable later via
the gear button.

## How it works (for maintainers)

```
┌────────────────────────── Premiere Pro ──────────────────────────┐
│  ┌───────────── Collaborate panel (CEP, HTML/JS) ─────────────┐     │
│  │  main.js ──child_process──▶ collab CLI ──▶ git repo/locks  │     │
│  │  main.js ──evalScript────▶ jsx/host.jsx (ExtendScript)  │     │
│  │                            open / save / close project  │     │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

All locking/git logic stays in the CLI — the panel shells out to `collab` with
`--json`/`--yes` flags (added for exactly this) and never reimplements any of
it. Premiere-side actions go through four small ExtendScript functions in
[jsx/host.jsx](../cep/com.collaborate.panel/jsx/host.jsx). The panel source lives in
[cep/com.collaborate.panel/](../cep/com.collaborate.panel/).

Known limitations:

- **A project must be open before the panel can open.** Premiere's
  Window → Extensions menu (like most of its workspace) is unavailable from the
  home screen. Practical pattern: keep a tiny always-available "Dashboard"
  project (even an empty .prproj outside the library) to open first; once the
  panel is in your workspace it stays there as you check projects out and in.
- **CEP, not UXP.** Adobe is migrating extensions to UXP; CEP still works in
  current Premiere releases, but a UXP port will eventually be needed. Note a
  UXP port is not a quick swap: UXP plugins can't spawn external processes, so
  the panel couldn't shell out to `collab` — it would need a small local service
  (e.g. `collab serve`) that the plugin talks to over localhost instead.
- **Unsigned** — needs PlayerDebugMode (the install script handles it).
- **New… requires a template.** Without a `template_path`, creating projects
  still needs the CLI flow (`collab new` in Terminal), which walks you through
  saving the project manually.
- **macOS only for now**, same as the launcher.
- If Premiere is closed mid-edit without checking in, the lock stays held —
  same behavior (and same recovery) as the CLI workflow.
