from decimal import Decimal
from uuid import UUID

from django.db import transaction

from easybiz.core.audit import service as audit
from easybiz.core.errors import DomainError
from easybiz.core.events import service as events
from easybiz.modules.timesheets import queries
from easybiz.modules.timesheets.enums import EntryStatus
from easybiz.modules.timesheets.models import Entry, Project
from easybiz.modules.timesheets.types import (
    CreateEntryParams,
    CreateProjectParams,
    EntryOut,
    ProjectOut,
    ReviewEntryParams,
    SubmitEntryParams,
)


class TimesheetError(DomainError):
    """A Timesheets domain-rule violation (maps to its HTTP status via the API handler)."""


def create_project(params: CreateProjectParams) -> ProjectOut:
    """Create a project with an uppercase, unique code."""
    code = params.code.upper()
    if queries.project_exists(code):
        raise TimesheetError(f"project {code!r} already exists", 409)
    project = Project.objects.create(code=code, name=params.name)
    audit.record(
        params.actor_id, "timesheets.project.created", entity="project", entity_id=str(project.id)
    )
    return ProjectOut.of(project)


def create_entry(params: CreateEntryParams) -> EntryOut:
    """Create a draft entry for the author against an active project."""
    if not (Decimal(0) < params.hours <= Decimal(24)) or params.hours != params.hours.quantize(
        Decimal("0.01")
    ):
        raise TimesheetError("hours must be in (0, 24] with at most 2 decimal places", 422)
    project = queries.active_project(params.project_id)
    if project is None:
        raise TimesheetError("project not found or inactive", 404)
    entry = Entry.objects.create(
        user_id=params.user_id,
        project=project,
        work_date=params.work_date,
        hours=params.hours,
        note=params.note,
    )
    return EntryOut.of(entry)


def submit_entry(params: SubmitEntryParams) -> EntryOut:
    """Submit the author's own draft or rejected entry."""
    entry = queries.own_entry(params.user_id, params.entry_id)
    if entry is None:
        raise TimesheetError("entry not found", 404)
    if entry.status not in (EntryStatus.DRAFT, EntryStatus.REJECTED):
        raise TimesheetError(f"cannot submit a {entry.status} entry", 409)
    entry.status = EntryStatus.SUBMITTED
    entry.save(update_fields=["status"])
    return EntryOut.of(entry)


def approve_entry(params: ReviewEntryParams) -> EntryOut:
    """Approve a submitted entry (not the reviewer's own); publishes timesheets.entry.approved."""
    return _review(params, EntryStatus.APPROVED, "timesheets.entry.approved")


def reject_entry(params: ReviewEntryParams) -> EntryOut:
    """Reject a submitted entry (not the reviewer's own); publishes timesheets.entry.rejected."""
    return _review(params, EntryStatus.REJECTED, "timesheets.entry.rejected")


def drop_user_drafts(user_id: UUID) -> None:
    """Delete a user's draft entries; submitted/approved/rejected time is kept."""
    Entry.objects.filter(user_id=user_id, status=EntryStatus.DRAFT).delete()


def _review(params: ReviewEntryParams, new_status: str, event_name: str) -> EntryOut:
    entry = queries.entry(params.entry_id)
    if entry is None:
        raise TimesheetError("entry not found", 404)
    if entry.status != EntryStatus.SUBMITTED:
        raise TimesheetError(f"entry is {entry.status}, not submitted", 409)
    if entry.user_id == params.reviewer_id:
        raise TimesheetError("cannot review your own time", 403)
    with transaction.atomic():
        entry.status = new_status
        entry.reviewed_by = params.reviewer_id
        entry.review_note = params.review_note
        entry.save(update_fields=["status", "reviewed_by", "review_note"])
        audit.record(
            params.reviewer_id,
            f"timesheets.entry.{new_status}",
            entity="entry",
            entity_id=str(entry.id),
        )
        events.publish(
            event_name,
            {
                "entry_id": str(entry.id),
                "user_id": str(entry.user_id),
                "project_id": str(entry.project_id),
                "work_date": entry.work_date.isoformat(),
                "hours": str(entry.hours),
            },
            producer="timesheets",
        )
    return EntryOut.of(entry)
