from uuid import UUID

from ninja import Router
from ninja.responses import Status

from easybiz.core.api.security import perm
from easybiz.core.iam import service as iam
from easybiz.modules.timesheets import commands, queries
from easybiz.modules.timesheets.types import (
    CreateEntryParams,
    CreateProjectParams,
    EntryIn,
    EntryOut,
    ProjectIn,
    ProjectOut,
    RejectIn,
    ReviewEntryParams,
    SubmitEntryParams,
)

router = Router()


def _can_approve(request) -> bool:
    return iam.has_permission(iam.permissions_for(request.auth.id), "timesheets.entry.approve")


@router.get("/projects", auth=perm("timesheets.project.read"), response=list[ProjectOut])
def list_projects(request):
    """Every project, ordered by code."""
    return queries.all_projects()


@router.post("/projects", auth=perm("timesheets.project.manage"), response={201: ProjectOut})
def create_project(request, data: ProjectIn):
    """Create a project; code is stored uppercase and must be unique (409)."""
    params = CreateProjectParams(actor_id=request.auth.id, **data.model_dump())
    return Status(201, commands.create_project(params))


@router.post("/entries", auth=perm("timesheets.entry.create"), response={201: EntryOut})
def create_entry(request, data: EntryIn):
    """Create a draft entry for the caller against an active project."""
    params = CreateEntryParams(user_id=request.auth.id, **data.model_dump())
    return Status(201, commands.create_entry(params))


@router.get("/entries", auth=perm("timesheets.entry.read"), response=list[EntryOut])
def list_entries(request, status: str | None = None, user_id: UUID | None = None):
    """Own entries for a plain reader; all entries (optionally filtered by user) for an approver."""
    return queries.entries_for(request.auth.id, _can_approve(request), status, user_id)


@router.post("/entries/{entry_id}/submit", auth=perm("timesheets.entry.create"), response=EntryOut)
def submit_entry(request, entry_id: UUID):
    """Submit the caller's own draft or rejected entry."""
    return commands.submit_entry(SubmitEntryParams(user_id=request.auth.id, entry_id=entry_id))


@router.post(
    "/entries/{entry_id}/approve", auth=perm("timesheets.entry.approve"), response=EntryOut
)
def approve_entry(request, entry_id: UUID):
    """Approve a submitted entry (not your own); publishes timesheets.entry.approved."""
    return commands.approve_entry(ReviewEntryParams(reviewer_id=request.auth.id, entry_id=entry_id))


@router.post("/entries/{entry_id}/reject", auth=perm("timesheets.entry.approve"), response=EntryOut)
def reject_entry(request, entry_id: UUID, data: RejectIn):
    """Reject a submitted entry (not your own); publishes timesheets.entry.rejected."""
    return commands.reject_entry(
        ReviewEntryParams(reviewer_id=request.auth.id, entry_id=entry_id, review_note=data.reason)
    )
