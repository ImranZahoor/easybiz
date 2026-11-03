from uuid import UUID

from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from easybiz.core.api.security import perm
from easybiz.core.iam import service as iam
from easybiz.modules.timesheets import commands, queries
from easybiz.modules.timesheets.models import Entry, Project
from easybiz.modules.timesheets.types import EntryIn, EntryOut, ProjectIn, ProjectOut, RejectIn

router = Router()


def _project_view(project: Project) -> ProjectOut:
    return ProjectOut(
        id=str(project.id), code=project.code, name=project.name, is_active=project.is_active
    )


def _entry_view(entry: Entry) -> EntryOut:
    return EntryOut(
        id=str(entry.id),
        user_id=str(entry.user_id),
        project_id=str(entry.project_id),
        work_date=entry.work_date.isoformat(),
        hours=str(entry.hours),
        note=entry.note,
        status=entry.status,
    )


def _can_approve(request) -> bool:
    return iam.has_permission(iam.permissions_for(request.auth.id), "timesheets.entry.approve")


@router.get("/projects", auth=perm("timesheets.project.read"), response=list[ProjectOut])
def list_projects(request):
    """Every project, ordered by code."""
    return [_project_view(p) for p in queries.all_projects()]


@router.post("/projects", auth=perm("timesheets.project.manage"), response={201: ProjectOut})
def create_project(request, data: ProjectIn):
    """Create a project; code is stored uppercase and must be unique (409)."""
    try:
        project = commands.create_project(request.auth.id, data.code, data.name)
    except commands.TimesheetError as exc:
        raise HttpError(exc.status, str(exc)) from exc
    return Status(201, _project_view(project))


@router.post("/entries", auth=perm("timesheets.entry.create"), response={201: EntryOut})
def create_entry(request, data: EntryIn):
    """Create a draft entry for the caller against an active project."""
    try:
        entry = commands.create_entry(
            request.auth.id, data.project_id, data.work_date, data.hours, data.note
        )
    except commands.TimesheetError as exc:
        raise HttpError(exc.status, str(exc)) from exc
    return Status(201, _entry_view(entry))


@router.get("/entries", auth=perm("timesheets.entry.read"), response=list[EntryOut])
def list_entries(request, status: str | None = None, user_id: UUID | None = None):
    """Own entries for a plain reader; all entries (optionally filtered by user) for an approver."""
    entries = queries.entries_for(request.auth.id, _can_approve(request), status, user_id)
    return [_entry_view(e) for e in entries]


@router.post("/entries/{entry_id}/submit", auth=perm("timesheets.entry.create"), response=EntryOut)
def submit_entry(request, entry_id: UUID):
    """Submit the caller's own draft or rejected entry."""
    try:
        entry = commands.submit_entry(request.auth.id, entry_id)
    except commands.TimesheetError as exc:
        raise HttpError(exc.status, str(exc)) from exc
    return _entry_view(entry)


@router.post(
    "/entries/{entry_id}/approve", auth=perm("timesheets.entry.approve"), response=EntryOut
)
def approve_entry(request, entry_id: UUID):
    """Approve a submitted entry (not your own); publishes timesheets.entry.approved."""
    try:
        entry = commands.approve_entry(request.auth.id, entry_id)
    except commands.TimesheetError as exc:
        raise HttpError(exc.status, str(exc)) from exc
    return _entry_view(entry)


@router.post("/entries/{entry_id}/reject", auth=perm("timesheets.entry.approve"), response=EntryOut)
def reject_entry(request, entry_id: UUID, data: RejectIn):
    """Reject a submitted entry (not your own); publishes timesheets.entry.rejected."""
    try:
        entry = commands.reject_entry(request.auth.id, entry_id, data.reason)
    except commands.TimesheetError as exc:
        raise HttpError(exc.status, str(exc)) from exc
    return _entry_view(entry)
