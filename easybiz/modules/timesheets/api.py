from decimal import Decimal

from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from easybiz.core.api.security import perm
from easybiz.core.audit import service as audit
from easybiz.core.iam import service as iam
from easybiz.modules.timesheets.models import Entry, Project
from easybiz.modules.timesheets.types import EntryIn, EntryOut, ProjectIn, ProjectOut

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
    return [_project_view(p) for p in Project.objects.order_by("code")]


@router.post("/projects", auth=perm("timesheets.project.manage"), response={201: ProjectOut})
def create_project(request, data: ProjectIn):
    """Create a project; code is stored uppercase and must be unique (409)."""
    code = data.code.upper()
    if Project.objects.filter(code=code).exists():
        raise HttpError(409, f"project {code!r} already exists")
    project = Project.objects.create(code=code, name=data.name)
    audit.record(
        request.auth.id, "timesheets.project.created", entity="project", entity_id=str(project.id)
    )
    return Status(201, _project_view(project))


@router.post("/entries", auth=perm("timesheets.entry.create"), response={201: EntryOut})
def create_entry(request, data: EntryIn):
    """Create a draft entry for the caller against an active project."""
    if not (Decimal(0) < data.hours <= Decimal(24)):
        raise HttpError(422, "hours must be in (0, 24]")
    project = Project.objects.filter(id=data.project_id, is_active=True).first()
    if project is None:
        raise HttpError(404, "project not found or inactive")
    entry = Entry.objects.create(
        user_id=request.auth.id,
        project=project,
        work_date=data.work_date,
        hours=data.hours,
        note=data.note,
    )
    return Status(201, _entry_view(entry))


@router.get("/entries", auth=perm("timesheets.entry.read"), response=list[EntryOut])
def list_entries(request, status: str | None = None, user_id: str | None = None):
    """Own entries for a plain reader; all entries (optionally filtered by user) for an approver."""
    entries = Entry.objects.all()
    if _can_approve(request):
        if user_id:
            entries = entries.filter(user_id=user_id)
    else:
        entries = entries.filter(user_id=request.auth.id)  # readers see only their own
    if status:
        entries = entries.filter(status=status)
    return [_entry_view(e) for e in entries.order_by("-work_date")]


@router.post("/entries/{entry_id}/submit", auth=perm("timesheets.entry.create"), response=EntryOut)
def submit_entry(request, entry_id: str):
    """Submit the caller's own draft or rejected entry."""
    entry = Entry.objects.filter(id=entry_id, user_id=request.auth.id).first()
    if entry is None:
        raise HttpError(404, "entry not found")
    if entry.status not in (Entry.DRAFT, Entry.REJECTED):
        raise HttpError(409, f"cannot submit a {entry.status} entry")
    entry.status = Entry.SUBMITTED
    entry.save(update_fields=["status"])
    return _entry_view(entry)
