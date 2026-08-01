# Getting Started with Open-DAM

*A guide for editors. No Git or programming experience needed.*

## What is this?

Open-DAM works like a library checkout system for Premiere Pro projects.

When a team shares Premiere projects, two people opening the same project at the
same time is a disaster — Premiere project files can't be merged, so one person's
work always gets thrown away. Open-DAM prevents that: before you edit a project,
you **check it out**. While you have it checked out, it's yours — nobody else can
open it through the system. When you're done, you **check it in**, which saves your
version for the whole team and frees it up for the next person.

Everything happens through a small tool called `dam` that you run in the Terminal
app. You only need four commands day to day, and this guide walks through all of
them.

**Your footage never moves.** Only the small Premiere project files are shared.
Everyone on the team keeps an identical copy of the raw media on their own drive,
in the same folder layout, so projects open with all media connected on every
machine.

## The three rules

1. **Always check a project out before opening it.** Never open a `.prproj` from
   this folder by double-clicking it in Finder.
2. **Always check it back in when you're done** (or release it if you changed
   nothing). A checked-out project is blocked for everyone else until you do.
3. **Save and close the project in Premiere before checking in.** The tool asks
   you to confirm this every time.

---

## Part 1 — One-time setup (about 15 minutes)

You'll do this once per computer. If any step feels unfamiliar, do it together
with the most technical person on your team — after this part, daily use is easy.

### Step 0: Open Terminal

Terminal is already on your Mac: press `Cmd+Space`, type `Terminal`, press Return.
You type a command at the prompt and press Return to run it. That's all the
Terminal knowledge this guide needs.

### Step 1: Install the `dam` tool

Ask your team lead for the install command for your team. It will look something
like this (one line, then Return):

```
python3 -m pip install git+https://github.com/YOUR-TEAM/Open-DAM.git
```

Then check it worked:

```
dam --help
```

You should see a list of commands. If Terminal says `command not found: dam`,
tell your team lead — it's a quick fix (the install location isn't on your PATH),
not something you broke.

### Step 2: Get access to your team's project library

Your team's projects live in a shared online library (a "repository" on GitHub —
your team lead set this up in Part 4 below). You need two things from your lead:

- An **invitation** to the repository (you'll need a free GitHub account —
  [github.com/signup](https://github.com/signup))
- The repository's **address**, which looks like
  `https://github.com/YOUR-TEAM/Premiere-Projects.git`

The first time you connect, your Mac will ask you to sign in to GitHub. If you
get stuck here, this is the step where teams most often help each other — it's a
one-time hurdle.

### Step 3: Download the project library to your Mac

In Terminal (replace the address with your team's real one):

```
dam clone https://github.com/YOUR-TEAM/Premiere-Projects.git --dir ~/Premiere-Projects
cd ~/Premiere-Projects
```

This creates a `Premiere-Projects` folder in your home folder and moves Terminal
into it. **This folder is where you'll run all `dam` commands from now on.** Any
time you open a new Terminal window, start with:

```
cd ~/Premiere-Projects
```

### Step 4: Answer the setup questions

```
dam init
```

The tool asks a few questions:

- **Your git user.email** — your email address. This is the name on your
  checkouts, so teammates can see who has a project.
- **Path to your local media root** — where the shared footage lives on your
  drive, for example `/Volumes/EDIT SSD/ProjectMedia`. Tip: you can drag the
  folder from Finder into the Terminal window and its location is typed for you.
- **Premiere Pro** — the tool usually finds your installed Premiere by itself and
  just tells you. If you have several versions, it asks you to pick one.
- **Template project** — optional; skip it by pressing Return (your team lead may
  give you a path to enter here later).

### Step 5: Confirm everything is ready

```
dam doctor
```

Every line should say `OK`. If `media_root` says `FAIL`, your external drive
probably isn't plugged in — plug it in and run `dam doctor` again. If anything
else says `FAIL`, send a screenshot to your team lead.

**Setup is done.** You never have to do any of that again.

---

## Part 2 — Everyday workflow

### See what's available

```
dam list
```

```
┏━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Project     ┃ Status   ┃ Locked by         ┃ Since                ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ Ep01        │ unlocked │ -                 │ -                    │
│ Ep02        │ locked   │ dana@example.com  │ 2026-07-15T18:20:00Z │
└─────────────┴──────────┴───────────────────┴──────────────────────┘
```

`unlocked` means available. `locked` means someone's working on it — you can see
who, and since when.

### Start working on a project

```
dam checkout Ep01
```

The tool grabs the latest version of the project, marks it as yours so nobody
else can take it, and opens it in Premiere Pro. Edit as normal — save as often
as you like.

### Finish working

Save your project in Premiere and close it. Then:

```
dam checkin Ep01
```

It asks *"Have you saved and closed the project in Premiere?"* — type `y` and
press Return. Your version is now saved to the team library and the project is
available for the next person. That's the whole loop:

> **checkout → edit in Premiere → save & close → checkin**

Prefer clicking to typing? There's a **[menu bar app](menubar-app.md)** that
puts this same loop in your Mac's top bar — see what's available and check
things out/in with one click, no Terminal needed once it's installed.

### Starting a brand-new project

```
dam new Ep03
```

If your team has a template configured, the new project is created from it and
opened in Premiere, already checked out to you. If not, a blank Premiere opens
and the tool tells you exactly where to save your new project — save it there,
come back to Terminal, and confirm.

### Leaving notes for each other

Every project has a to-do list attached — the tool calls them tickets. **You
don't need to check a project out to add one**, so a producer or another editor
can flag work on a project any time:

```
dam ticket add Ep01 "Fix audio sync at 02:14"
```

Whoever checks Ep01 out next sees the open tickets right in their Terminal,
before Premiere even opens. To see or close them:

```
dam ticket list Ep01           # every ticket, open and done
dam ticket done Ep01 a3f2      # mark one done (use the id from the list)
```

And when you finish a session, you can leave a note for the next editor as part
of checking in:

```
dam checkin Ep01 --note "rough cut done, still needs color"
```

### Adding a project that already exists (from before your team used Open-DAM)

```
dam import ~/Desktop/OldProject.prproj
```

This copies the project into the team library. Add `--checkout` to start
working on it right away.

---

## Part 3 — Common situations

**"I want to work on Ep02 but it's locked by someone else."**
That's the system working. Ask them to `dam checkin` (if they're done) or wait.
There is deliberately no way to take it without them (or an admin) agreeing.

**"I need to step away but I'm not finished."**
You have two options:
- Keep it checked out (do nothing) — fine for lunch, blocks others until you're back.
- Save a snapshot for safety but keep the project yours:
  ```
  dam checkin Ep01 --keep-lock
  ```

**"I opened a project, changed nothing, and want out."**
```
dam release Ep01
```
Frees the project without saving a new version.

**"I made a mess and want to throw away everything since my checkout."**
```
dam release Ep01 --discard-local
```
It asks you to confirm — this permanently discards your changes since checkout,
and the project goes back to the version in the team library.

**"Dana went on vacation with Ep02 checked out."**
An admin (usually the team lead) can force it free:
```
dam release Ep02 --force
```
It asks you to type the project name to confirm, and the takeover is recorded so
everyone can see who did it and when. Talk to the person first if you can — any
work they hadn't checked in stays only on their machine.

**"I'm not sure what state things are in."**
```
dam status Ep01
```
Shows who has it, since when, and whether you have unsaved-to-team changes.

---

## Part 4 — For the team lead: setting up a new team library

This is the one-time creation of the shared repository your editors will clone
in Part 1. You'll need a GitHub account and the `dam` tool installed (Part 1,
Steps 0–1).

1. **Create an empty repository on GitHub.** On github.com: **New repository** →
   name it (e.g. `Premiere-Projects`) → set it to **Private** → **Create**.
   Don't add a README or any starter files — leave it completely empty.

2. **Clone it and set yourself up:**
   ```
   dam clone https://github.com/YOUR-TEAM/Premiere-Projects.git --dir ~/Premiere-Projects
   cd ~/Premiere-Projects
   dam init
   ```

3. **Add your first projects.** Import existing ones, or start fresh:
   ```
   dam import ~/OldProjects/Ep01.prproj
   dam new Ep02
   ```

4. **Agree on a media layout.** Decide the folder structure for raw footage
   (e.g. `/Volumes/EDIT SSD/ProjectMedia/...`) and make sure every editor copies
   the media to the *same place* on their own drive. This is what keeps projects
   opening with no offline media on every machine. Optional but recommended:
   before importing, set each Premiere project to use relative paths so links
   survive the move between machines.

5. **Optional: create a template project** (sequences, bins, and settings your
   team always starts from), and have each editor enter its path during
   `dam init` — then `dam new` starts every project from it. Two rules for the
   template file:
   - **Keep it outside the library folder** (e.g. on the shared media drive) —
     never point the template at a project that lives inside the library.
   - **Don't have it open in Premiere** when someone runs `dam new`. Copying a
     project Premiere currently has open confuses Premiere into leaving stray
     rescue copies behind (see Part 5).

6. **Invite your editors.** On the GitHub repository page: **Settings →
   Collaborators → Add people.** Then send them the repository address and point
   them at Part 1 of this guide.

---

## Part 5 — When something goes wrong

| The tool says... | What it means | What to do |
|---|---|---|
| `'Ep01' is already checked out by <name>` | Someone has it | Wait, or ask them to check it in |
| `not inside a DAM git repo` | Terminal isn't in the project folder | `cd ~/Premiere-Projects` and try again |
| `No project named 'X' found` | Typo, or the project doesn't exist | `dam list` to see the real names |
| `Lock is no longer yours` | An admin force-released your checkout while you worked | Talk to your team; `--force-checkin` can still save your version if it should win |
| `Lock acquired, but could not launch Premiere` | Your checkout worked; only the app launch failed | Run `dam doctor`; open the `.prproj` manually this once |
| `could not reach remote` / network errors | No internet, or GitHub sign-in problem | Check your connection, retry; if it persists, ask your lead |
| `remote is contended, try again shortly` | Rare traffic jam — several people syncing at the exact same moment | Just run the command again |
| Premiere opens but all media is offline | Your external drive isn't mounted, or its folder layout doesn't match the team's | Plug the drive in and reopen; `dam doctor` confirms the media path |
| `'X' has local uncommitted changes` | A previous session didn't finish cleanly | `dam checkin X` to save it, or `dam release X --discard-local` to throw it away |
| A weird project appears in `dam list`, named like `Ep01--edebf705-…-2026-07-15_22-20-28` | A rescue copy Premiere made — usually because a project was copied or changed while Premiere had it open (e.g. a template that lives inside the library) | Safe to delete the file; move your template outside the library folder |

Still stuck? Run `dam doctor`, screenshot the output, and send it to your team
lead — it checks all the usual suspects at once.

## Cheat sheet

```
dam list                          what's available, who has what
dam checkout <project>            start working (opens Premiere)
dam checkin <project>             done working (saves + frees it)
dam release <project>             changed your mind, changed nothing
dam new <project>                 brand-new project
dam import <file>                 bring an existing .prproj into the library
dam status <project>              details on one project
dam doctor                        is everything set up right?
dam ticket add <project> "note"   flag work on a project (no checkout needed)
dam ticket list <project>         see a project's to-do list
dam ticket done <project> <id>    mark a to-do done
dam checkin <project> --note "…"  check in + leave a note for the next editor
dam menubar                       launch the menu bar app (top-bar buttons, no terminal)
```
