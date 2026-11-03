from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db import transaction

from easybiz.core.audit import service as audit
from easybiz.core.events import service as events
from easybiz.modules.timesheets import queries
from easybiz.modules.timesheets.models import Entry, Project


class TimesheetError(Exception):
    """A domain rule violation carrying the HTTP status the API should return."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def create_project(actor_id: UUID, code: str, name: str) -> Project:
    """Create a project with an uppercase, unique code."""
    code = code.upper()
    if queries.project_exists(code):
        raise TimesheetError(f"project {code!r} already exists", 409)
    project = Project.objects.create(code=code, name=name)
    audit.record(
        actor_id, "timesheets.project.created", entity="project", entity_id=str(project.id)
    )
    return project


def create_entry(
    user_id: UUID, project_id: UUID, work_date: date, hours: Decimal, note: str
) -> Entry:
    """Create a draft entry for the user against an active project."""
    if not (Decimal(0) < hours <= Decimal(24)) or hours != hours.quantize(Decimal("0.01")):
        raise TimesheetError("hours must be in (0, 24] with at most 2 decimal places", 422)
    project = queries.active_project(project_id)
    if project is None:
        raise TimesheetError("project not found or inactive", 404)
    return Entry.objects.create(
        user_id=user_id, project=project, work_date=work_date, hours=hours, note=note
    )


def submit_entry(user_id: UUID, entry_id: UUID) -> Entry:
    """Submit the user's own draft or rejected entry."""
    entry = queries.own_entry(user_id, entry_id)
    if entry is None:
        raise TimesheetError("entry not found", 404)
    if entry.status not in (Entry.DRAFT, Entry.REJECTED):
        raise TimesheetError(f"cannot submit a {entry.status} entry", 409)
    entry.status = Entry.SUBMITTED
    entry.save(update_fields=["status"])
    return entry


def approve_entry(reviewer_id: UUID, entry_id: UUID) -> Entry:
    """Approve a submitted entry (not the reviewer's own); publishes timesheets.entry.approved."""
    return _review(reviewer_id, entry_id, Entry.APPROVED, "timesheets.entry.approved")


def reject_entry(reviewer_id: UUID, entry_id: UUID, reason: str = "") -> Entry:
    """Reject a submitted entry (not the reviewer's own); publishes timesheets.entry.rejected."""
    return _review(reviewer_id, entry_id, Entry.REJECTED, "timesheets.entry.rejected", reason)


def drop_user_drafts(user_id: UUID) -> None:
    """Delete a user's draft entries; submitted/approved/rejected time is kept."""
    Entry.objects.filter(user_id=user_id, status=Entry.DRAFT).delete()


def _review(
    reviewer_id: UUID, entry_id: UUID, new_status: str, event_name: str, review_note: str = ""
) -> Entry:
    entry = queries.entry(entry_id)
    if entry is None:
        raise TimesheetError("entry not found", 404)
    if entry.status != Entry.SUBMITTED:
        raise TimesheetError(f"entry is {entry.status}, not submitted", 409)
    if entry.user_id == reviewer_id:
        raise TimesheetError("cannot review your own time", 403)
    with transaction.atomic():
        entry.status = new_status
        entry.reviewed_by = reviewer_id
        entry.review_note = review_note
        entry.save(update_fields=["status", "reviewed_by", "review_note"])
        audit.record(
            reviewer_id, f"timesheets.entry.{new_status}", entity="entry", entity_id=str(entry.id)
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
    return entry
