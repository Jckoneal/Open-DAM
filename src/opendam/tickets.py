"""Tickets: lightweight notes attached to a project, one JSON file per ticket.

Tickets live in a sibling directory of the project file
(`Ep01.prproj.tickets/<id>.json`). One file per ticket — not a shared
tickets.json — so two people adding tickets to the same project concurrently
touch different files and no git conflict is possible, mirroring the
per-project lock file design. Adding a ticket requires no lock: that's the
point — anyone can flag work on a project without checking it out.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from opendam.errors import OpenDamError
from opendam.locking import utcnow_iso

SCHEMA_VERSION = 1


class TicketNotFoundError(OpenDamError):
    pass


@dataclass
class Ticket:
    schema_version: int
    id: str
    text: str
    created_by: dict
    created_at: str
    status: str  # "open" | "done"
    done_by: Optional[dict] = None
    done_at: Optional[str] = None

    @classmethod
    def load(cls, path: Path) -> "Ticket":
        data = json.loads(path.read_text())
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")

    def is_open(self) -> bool:
        return self.status == "open"


def tickets_dir_for(project_file: Path) -> Path:
    return project_file.with_suffix(project_file.suffix + ".tickets")


def ticket_path(project_file: Path, ticket_id: str) -> Path:
    return tickets_dir_for(project_file) / f"{ticket_id}.json"


def load_all(project_file: Path) -> list[Ticket]:
    tdir = tickets_dir_for(project_file)
    if not tdir.is_dir():
        return []
    # created_at (from locking.utcnow_iso) only has whole-second resolution,
    # so two tickets added within the same second tie there; without a
    # tiebreaker, sort order falls back to filesystem glob order, which is
    # OS-dependent, not creation order. File mtime has sub-second resolution
    # on any filesystem we run on and reflects real write order, since each
    # `dam ticket add` writes its file synchronously before returning.
    pairs = [(Ticket.load(p), p.stat().st_mtime) for p in tdir.glob("*.json")]
    pairs.sort(key=lambda pair: (pair[0].created_at, pair[1]))
    return [ticket for ticket, _mtime in pairs]


def open_tickets(project_file: Path) -> list[Ticket]:
    return [t for t in load_all(project_file) if t.is_open()]


def create(project_file: Path, text: str, identity: dict) -> Ticket:
    """Write a new open ticket's file. Caller owns the git add/commit/push."""
    ticket = Ticket(
        schema_version=SCHEMA_VERSION,
        id=uuid.uuid4().hex[:8],
        text=text,
        created_by=identity,
        created_at=utcnow_iso(),
        status="open",
    )
    tdir = tickets_dir_for(project_file)
    tdir.mkdir(parents=True, exist_ok=True)
    ticket.save(ticket_path(project_file, ticket.id))
    return ticket


def find_by_prefix(project_file: Path, id_prefix: str) -> Ticket:
    matches = [t for t in load_all(project_file) if t.id.startswith(id_prefix)]
    if not matches:
        raise TicketNotFoundError(
            f"No ticket starting with '{id_prefix}' on {project_file.stem}. "
            f"Run 'dam ticket list {project_file.stem}' to see ticket ids."
        )
    if len(matches) > 1:
        ids = ", ".join(t.id for t in matches)
        raise TicketNotFoundError(f"'{id_prefix}' is ambiguous — matches: {ids}. Use more characters.")
    return matches[0]


def mark_done(project_file: Path, ticket: Ticket, identity: dict) -> Ticket:
    """Rewrite the ticket's file as done. Caller owns the git add/commit/push."""
    ticket.status = "done"
    ticket.done_by = identity
    ticket.done_at = utcnow_iso()
    ticket.save(ticket_path(project_file, ticket.id))
    return ticket
