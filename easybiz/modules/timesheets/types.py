from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from ninja import Schema

from easybiz.modules.timesheets.enums import EntryStatus

# --- Projects ----------------------------------------------------------------


class ProjectFields(Schema):
    code: str
    name: str


class ProjectIn(ProjectFields):
    """Create-project request body."""


class CreateProjectParams(ProjectFields):
    """Command input: request fields plus the server-derived actor."""

    actor_id: UUID


class ProjectOut(Schema):
    id: str
    code: str
    name: str
    is_active: bool

    @classmethod
    def of(cls, project) -> ProjectOut:
        return cls(
            id=str(project.id), code=project.code, name=project.name, is_active=project.is_active
        )


# --- Entries -----------------------------------------------------------------


class EntryFields(Schema):
    project_id: UUID
    work_date: date
    hours: Decimal
    note: str = ""


class EntryIn(EntryFields):
    """Create-entry request body."""


class CreateEntryParams(EntryFields):
    """Command input: request fields plus the server-derived author."""

    user_id: UUID


class SubmitEntryParams(Schema):
    user_id: UUID
    entry_id: UUID


class ReviewEntryParams(Schema):
    reviewer_id: UUID
    entry_id: UUID
    review_note: str = ""


class RejectIn(Schema):
    reason: str = ""


class EntryOut(Schema):
    id: str
    user_id: str
    project_id: str
    work_date: str
    hours: str
    note: str
    status: EntryStatus

    @classmethod
    def of(cls, entry) -> EntryOut:
        return cls(
            id=str(entry.id),
            user_id=str(entry.user_id),
            project_id=str(entry.project_id),
            work_date=entry.work_date.isoformat(),
            hours=str(entry.hours),
            note=entry.note,
            status=entry.status,
        )
