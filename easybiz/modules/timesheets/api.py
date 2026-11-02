from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from easybiz.core.api.security import perm
from easybiz.core.audit import service as audit
from easybiz.modules.timesheets.models import Project
from easybiz.modules.timesheets.types import ProjectIn, ProjectOut

router = Router()


def _project_view(project: Project) -> ProjectOut:
    return ProjectOut(
        id=str(project.id), code=project.code, name=project.name, is_active=project.is_active
    )


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
