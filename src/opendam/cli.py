from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from opendam import config as config_mod
from opendam import git_ops
from opendam import locking
from opendam import projects as projects_mod
from opendam.errors import (
    DirtyWorkingTreeError,
    LockHeldError,
    OpenDamError,
    ProjectNotFoundError,
)
from opendam.launcher import get_launcher

app = typer.Typer(help="Git-based checkout manager for Adobe Premiere Pro projects.")
console = Console()


def _repo(ctx_path: Optional[str] = None) -> Path:
    return Path(ctx_path or Path.cwd()).resolve()


def _fail(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _push_with_retry(repo_path: Path) -> None:
    """Push local commits, rebasing onto unrelated remote advances on
    rejection. Safe because the lock invariant guarantees nobody else
    touches the files we ourselves just committed."""
    for _ in range(locking.MAX_CLAIM_RETRIES):
        push_result = git_ops.push(repo_path)
        if push_result.ok:
            return
        if git_ops.is_push_rejected(push_result):
            rebase_result = git_ops.pull_rebase(repo_path)
            if not rebase_result.ok:
                git_ops.run_git(["rebase", "--abort"], repo_path, check=False)
                _fail(f"could not integrate remote changes: {rebase_result.stderr}")
                return
            continue
        _fail(f"push failed: {push_result.stderr}")
        return
    _fail("Could not push — remote is contended, try again shortly.")


@app.command()
def init(repo: str = typer.Option(".", help="Path to the DAM git repo")) -> None:
    """Interactive wizard: git identity, media root, Premiere discovery -> .damconfig.yaml"""
    repo_path = _repo(repo)
    cfg = config_mod.Config.load(repo_path)

    email = git_ops.get_config(repo_path, "user.email")
    if not email:
        email = typer.prompt("Your git user.email (used to attribute locks)")
        git_ops.run_git(["config", "--global", "user.email", email], repo_path)

    media_root = typer.prompt(
        "Path to your local media root (same relative layout as other editors)",
        default=cfg.media_root or "",
    )
    cfg.media_root = media_root or None
    if cfg.media_root and not Path(cfg.media_root).exists():
        console.print(f"[yellow]Warning:[/yellow] media_root '{cfg.media_root}' does not exist on this machine yet.")

    candidates = config_mod.discover_premiere()
    if candidates:
        if len(candidates) == 1:
            cfg.premiere.app_path = candidates[0]
            console.print(f"Found Premiere Pro: {candidates[0]}")
        else:
            console.print("Multiple Premiere Pro versions found:")
            for i, c in enumerate(candidates):
                console.print(f"  [{i}] {c}")
            idx = typer.prompt("Pick one", default="0")
            cfg.premiere.app_path = candidates[int(idx)]
    else:
        console.print("[yellow]No Premiere Pro installation auto-discovered.[/yellow]")
        manual = typer.prompt("Path to Premiere Pro app (leave blank to skip)", default="")
        cfg.premiere.app_path = manual or None

    template = typer.prompt(
        "Path to a template .prproj for 'dam new' (leave blank to skip)",
        default=cfg.template_path or "",
    )
    cfg.template_path = template or None

    cfg.save(repo_path)
    _ensure_gitignored(repo_path)
    console.print(f"[green]Wrote {config_mod.CONFIG_FILENAME}[/green]")
    doctor(repo=repo)


def _ensure_gitignored(repo_path: Path) -> None:
    gi = repo_path / ".gitignore"
    entry = config_mod.CONFIG_FILENAME
    existing = gi.read_text() if gi.exists() else ""
    if entry not in existing.splitlines():
        with gi.open("a") as f:
            f.write(f"\n{entry}\n")


@app.command()
def clone(remote_url: str, dir: Optional[str] = typer.Option(None, "--dir")) -> None:
    """Clone the DAM repo and set up local config."""
    dest = Path(dir).resolve() if dir else Path.cwd() / Path(remote_url).stem
    git_ops.clone(remote_url, dest)
    cfg = config_mod.Config.load(dest)
    cfg.remote = remote_url
    cfg.save(dest)
    _ensure_gitignored(dest)
    console.print(f"[green]Cloned into {dest}[/green]. Run 'dam init' inside it next.")


def _resolve_new_path(repo_path: Path, name: str) -> Path:
    target = name if name.endswith(".prproj") else f"{name}.prproj"
    target_path = repo_path / target
    if target_path.exists():
        _fail(f"'{target}' already exists in the repo.")
    return target_path


def _register_new_project(repo_path: Path, target_path: Path, commit_msg: str) -> None:
    """Commit a freshly created/imported .prproj (its lock is claimed
    separately) — a plain add+commit+push, no locking concerns yet since
    nobody else's clone knows this project exists until this lands."""
    git_ops.add(repo_path, [str(target_path)])
    result = git_ops.commit(repo_path, commit_msg)
    if not result.ok and "nothing to commit" not in result.stdout.lower():
        _fail(f"commit failed: {result.stderr}")
        return
    git_ops.fetch(repo_path)
    git_ops.pull_ff_only(repo_path)
    _push_with_retry(repo_path)


def _claim_and_launch(repo_path: Path, target_path: Path, cfg: "config_mod.Config", no_launch: bool) -> None:
    lock = locking.claim_lock(repo_path, target_path)
    console.print(f"[green]Checked out {target_path.stem}[/green] — locked by you as of {lock.locked_at}.")
    console.print(f"Run 'dam checkin {target_path.stem}' when done.")
    if no_launch:
        return
    launcher = get_launcher()
    try:
        launcher.launch(target_path, cfg.premiere.app_path or cfg.premiere.exe_path)
    except OpenDamError as e:
        console.print(f"[yellow]Lock acquired, but could not launch Premiere:[/yellow] {e}")
        console.print("Run 'dam doctor' to diagnose, or open the project manually.")


@app.command()
def new(
    name: str,
    repo: str = typer.Option(".", help="Path to the DAM repo"),
    no_launch: bool = typer.Option(False, "--no-launch"),
) -> None:
    """Create a brand-new Premiere project, register it, and claim the lock."""
    repo_path = _repo(repo)
    target_path = _resolve_new_path(repo_path, name)

    git_ops.fetch(repo_path)
    git_ops.pull_ff_only(repo_path)

    cfg = config_mod.Config.load(repo_path)
    app_path = cfg.premiere.app_path or cfg.premiere.exe_path
    launched_already = False

    if cfg.template_path and Path(cfg.template_path).exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(cfg.template_path, target_path)
        console.print(f"Created '{target_path.name}' from template.")
    else:
        console.print(
            f"No template configured — create a new project in Premiere and save it at:\n  {target_path}"
        )
        if not no_launch:
            try:
                get_launcher().launch_blank(app_path)
                launched_already = True
            except OpenDamError as e:
                console.print(f"[yellow]Could not launch Premiere automatically:[/yellow] {e}")
        if not typer.confirm(f"Have you saved the new project at {target_path}?"):
            console.print("Aborted — nothing created.")
            return
        if not target_path.exists():
            _fail(f"No file found at {target_path}. Save your project there and re-run 'dam new {name}'.")
            return

    identity = locking.current_identity(repo_path)
    _register_new_project(repo_path, target_path, f"new project: {target_path.name} by {identity['user']}")
    _claim_and_launch(repo_path, target_path, cfg, no_launch=no_launch or launched_already)


@app.command(name="import")
def import_project(
    source: str,
    name: Optional[str] = typer.Argument(None, help="Destination name inside the repo (default: source's filename)"),
    repo: str = typer.Option(".", help="Path to the DAM repo"),
    move: bool = typer.Option(False, "--move", help="Remove the source file after a successful import"),
    checkout_after: bool = typer.Option(False, "--checkout", help="Claim the lock and launch Premiere after importing"),
) -> None:
    """Bring an existing .prproj file under Open-DAM management."""
    repo_path = _repo(repo)
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists() or source_path.suffix != ".prproj":
        _fail(f"'{source}' is not an existing .prproj file.")
        return

    target_path = _resolve_new_path(repo_path, name or source_path.name)

    git_ops.fetch(repo_path)
    git_ops.pull_ff_only(repo_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source_path, target_path)

    identity = locking.current_identity(repo_path)
    _register_new_project(repo_path, target_path, f"import: {target_path.name} by {identity['user']}")
    console.print(f"[green]Imported {target_path.name}[/green].")

    if move:
        source_path.unlink()
        console.print(f"Removed original file at {source_path}.")

    if checkout_after:
        cfg = config_mod.Config.load(repo_path)
        _claim_and_launch(repo_path, target_path, cfg, no_launch=False)


@app.command(name="list")
def list_projects(repo: str = typer.Option(".", help="Path to the DAM repo")) -> None:
    """List all projects found in the repo."""
    repo_path = _repo(repo)
    table = Table("Project", "Status", "Locked by", "Since")
    for p in projects_mod.discover(repo_path):
        if p.lock and p.lock.is_locked():
            holder = p.lock.locked_by.get("user", "?")
            since = p.lock.locked_at or "?"
            table.add_row(p.name, "[red]locked[/red]", holder, since)
        else:
            table.add_row(p.name, "[green]unlocked[/green]", "-", "-")
    console.print(table)


@app.command()
def status(
    project: Optional[str] = typer.Argument(None),
    repo: str = typer.Option(".", help="Path to the DAM repo"),
) -> None:
    """Detailed lock + working-tree status for one project, or all if omitted."""
    repo_path = _repo(repo)
    if project is None:
        list_projects(repo=repo)
        return
    try:
        info = projects_mod.find(repo_path, project)
    except ProjectNotFoundError as e:
        _fail(str(e))
        return

    console.print(f"[bold]{info.name}[/bold]  ({info.path.relative_to(repo_path)})")
    if info.lock and info.lock.is_locked():
        console.print(f"  status:    [red]locked[/red]")
        console.print(f"  locked by: {info.lock.locked_by.get('user')} on {info.lock.locked_by.get('hostname')}")
        console.print(f"  since:     {info.lock.locked_at}")
    else:
        console.print("  status:    [green]unlocked[/green]")
    dirty = git_ops.status_porcelain(repo_path, [str(info.path)])
    console.print(f"  local:     {'dirty' if dirty else 'clean'}")


@app.command()
def checkout(
    project: str,
    repo: str = typer.Option(".", help="Path to the DAM repo"),
    no_launch: bool = typer.Option(False, "--no-launch"),
    force: bool = typer.Option(False, "--force", help="Seize an already-locked project (admin override)"),
) -> None:
    """Pull latest, claim the lock, and launch Premiere on the project."""
    repo_path = _repo(repo)
    try:
        info = projects_mod.find(repo_path, project)
    except ProjectNotFoundError as e:
        _fail(str(e))
        return

    own_dirty = git_ops.status_porcelain(repo_path, [str(info.path)])
    if own_dirty:
        _fail(
            f"'{info.name}' has local uncommitted changes already — "
            "resolve with 'dam checkin' or 'git' before checking out again."
        )
        return

    try:
        if force:
            identity = locking.current_identity(repo_path)
            confirm = typer.prompt(
                f"Type '{info.name}' to confirm forcibly seizing this lock"
            )
            if confirm != info.name:
                _fail("Confirmation text did not match — aborted.")
                return
            locking.release_lock(repo_path, info.path, identity, force=True, forced_by=identity)
            git_ops.add(repo_path, [str(locking.lock_path_for(info.path))])
            git_ops.commit(repo_path, f"FORCE-UNLOCK: {info.name} by {identity['user']}")
            _push_with_retry(repo_path)
        cfg = config_mod.Config.load(repo_path)
        _claim_and_launch(repo_path, info.path, cfg, no_launch=no_launch)
    except LockHeldError as e:
        _fail(str(e))
        return
    except OpenDamError as e:
        _fail(str(e))
        return


@app.command()
def checkin(
    project: str,
    repo: str = typer.Option(".", help="Path to the DAM repo"),
    message: Optional[str] = typer.Option(None, "-m", "--message"),
    force_checkin: bool = typer.Option(False, "--force-checkin"),
    keep_lock: bool = typer.Option(False, "--keep-lock"),
) -> None:
    """Commit + push project changes and release the lock."""
    repo_path = _repo(repo)
    try:
        info = projects_mod.find(repo_path, project)
    except ProjectNotFoundError as e:
        _fail(str(e))
        return

    identity = locking.current_identity(repo_path)
    if info.lock and info.lock.is_locked() and not info.lock.is_held_by(identity["user"]) and not force_checkin:
        _fail(
            f"Lock is no longer yours (held by {info.lock.locked_by.get('user')}). "
            "Use --force-checkin to commit+push anyway."
        )
        return

    launcher = get_launcher()
    still_open_hint = ""
    if launcher.is_running():
        still_open_hint = " (Premiere still appears to be running — have you saved?)"
    if not typer.confirm(f"Have you saved and closed the project in Premiere?{still_open_hint}"):
        console.print("Aborted — nothing committed.")
        return

    dirty = git_ops.status_porcelain(repo_path, [str(info.path)])
    to_add = [str(info.path)]
    if dirty:
        git_ops.add(repo_path, to_add)

    if not keep_lock:
        released = locking.release_lock(repo_path, info.path, identity)
        git_ops.add(repo_path, [str(locking.lock_path_for(info.path))])

    commit_msg = message or f"checkin: {info.name} by {identity['user']}"
    if dirty or not keep_lock:
        result = git_ops.commit(repo_path, commit_msg)
        if not result.ok and "nothing to commit" not in result.stdout.lower():
            _fail(f"commit failed: {result.stderr}")
            return

    git_ops.fetch(repo_path)
    git_ops.pull_ff_only(repo_path)
    _push_with_retry(repo_path)

    if keep_lock:
        console.print(f"[green]Checked in {info.name}[/green] — lock retained.")
    else:
        console.print(f"[green]Checked in {info.name}[/green] and released the lock.")


@app.command()
def release(
    project: str,
    repo: str = typer.Option(".", help="Path to the DAM repo"),
    force: bool = typer.Option(False, "--force"),
    discard_local: bool = typer.Option(False, "--discard-local"),
) -> None:
    """Release the lock without committing project changes."""
    repo_path = _repo(repo)
    try:
        info = projects_mod.find(repo_path, project)
    except ProjectNotFoundError as e:
        _fail(str(e))
        return

    identity = locking.current_identity(repo_path)
    forced_by = None
    if info.lock and info.lock.is_locked() and not info.lock.is_held_by(identity["user"]):
        if not force:
            _fail(
                f"Lock is held by {info.lock.locked_by.get('user')} — use --force to override."
            )
            return
        confirm = typer.prompt(f"Type '{info.name}' to confirm forced release")
        if confirm != info.name:
            _fail("Confirmation text did not match — aborted.")
            return
        forced_by = identity

    if discard_local:
        dirty = git_ops.status_porcelain(repo_path, [str(info.path)])
        if dirty and not typer.confirm(f"This will discard local changes to {info.name}. Continue?"):
            console.print("Aborted.")
            return
        git_ops.run_git(["checkout", "--", str(info.path)], repo_path, check=False)

    locking.release_lock(repo_path, info.path, identity, force=force, forced_by=forced_by)
    git_ops.add(repo_path, [str(locking.lock_path_for(info.path))])
    msg = (
        f"FORCE-UNLOCK: {info.name} by {identity['user']}" if forced_by
        else f"release: {info.name} by {identity['user']}"
    )
    git_ops.commit(repo_path, msg)
    git_ops.fetch(repo_path)
    git_ops.pull_ff_only(repo_path)
    _push_with_retry(repo_path)
    console.print(f"[green]Released {info.name}[/green].")


config_app = typer.Typer(help="Get/set values in .damconfig.yaml")
app.add_typer(config_app, name="config")


@config_app.command("get")
def config_get(key: Optional[str] = typer.Argument(None), repo: str = typer.Option(".")) -> None:
    cfg = config_mod.Config.load(_repo(repo))
    data = cfg.__dict__
    if key is None:
        console.print(data)
        return
    parts = key.split(".")
    value = data
    try:
        for part in parts:
            value = value[part] if isinstance(value, dict) else getattr(value, part)
    except (KeyError, AttributeError):
        _fail(f"Unknown config key '{key}'. Run 'dam config get' to see available keys.")
        return
    console.print(value)


@config_app.command("set")
def config_set(key: str, value: str, repo: str = typer.Option(".")) -> None:
    """Set a config value. Nested sections (currently just 'premiere') must be
    addressed with a dotted key, e.g. 'premiere.app_path' — setting the bare
    section name would otherwise overwrite it with a plain string and corrupt
    the config file for every later command that reads it."""
    repo_path = _repo(repo)
    cfg = config_mod.Config.load(repo_path)
    parts = key.split(".")

    if parts[0] == "premiere":
        if len(parts) != 2 or parts[1] not in config_mod.PremiereConfig.__dataclass_fields__:
            _fail("'premiere' is a section, not a settable value — use 'premiere.app_path' or 'premiere.exe_path'.")
            return
        setattr(cfg.premiere, parts[1], value)
    elif len(parts) == 1 and parts[0] in cfg.__dataclass_fields__:
        setattr(cfg, parts[0], value)
    else:
        _fail(f"Unknown config key '{key}'. Run 'dam config get' to see available keys.")
        return

    cfg.save(repo_path)
    console.print(f"[green]Set {key} = {value}[/green]")


@app.command()
def doctor(repo: str = typer.Option(".", help="Path to the DAM repo")) -> None:
    """Diagnostics: git present, remote reachable, Premiere found, media_root exists."""
    repo_path = _repo(repo)
    cfg = config_mod.Config.load(repo_path)

    checks = []
    checks.append(("git installed", shutil.which("git") is not None))

    email = git_ops.get_config(repo_path, "user.email")
    checks.append((f"git identity configured ({email or 'none'})", bool(email)))

    remote_ok = False
    try:
        git_ops.fetch(repo_path)
        remote_ok = True
    except OpenDamError:
        remote_ok = False
    checks.append(("remote reachable", remote_ok))

    media_ok = bool(cfg.media_root and Path(cfg.media_root).exists())
    checks.append((f"media_root exists ({cfg.media_root or 'not set'})", media_ok))

    premiere_path = cfg.premiere.app_path or cfg.premiere.exe_path
    premiere_ok = bool(premiere_path and Path(premiere_path).exists())
    checks.append((f"Premiere found ({premiere_path or 'not set'})", premiere_ok))

    for label, ok in checks:
        mark = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        console.print(f"  [{mark}] {label}")


if __name__ == "__main__":
    app()
