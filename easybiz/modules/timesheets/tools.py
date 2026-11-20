from easybiz.core.iam import service as iam
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool, registry
from easybiz.modules.timesheets import commands, queries
from easybiz.modules.timesheets.types import CreateProjectParams, ProjectIn


def _projects(user_id, params):
    return [p.model_dump() for p in queries.all_projects()]


def _entries(user_id, params):
    can_all = iam.has_permission(iam.permissions_for(user_id), "timesheets.entry.approve")
    return [e.model_dump() for e in queries.entries_for(user_id, can_all)]


def _create_project(user_id, params):
    out = commands.create_project(CreateProjectParams(actor_id=user_id, **params.model_dump()))
    return out.model_dump()


_TOOLS = [
    Tool(
        name="timesheets.projects.list",
        description="Projects in this tenant.",
        tier=ToolTier.READ,
        perm="timesheets.project.read",
        idempotent=True,
        input_schema=None,
        handler=_projects,
        module_id="timesheets",
    ),
    Tool(
        name="timesheets.entries.list",
        description="Time entries (own for a reader; all for an approver).",
        tier=ToolTier.READ,
        perm="timesheets.entry.read",
        idempotent=True,
        input_schema=None,
        handler=_entries,
        module_id="timesheets",
    ),
    Tool(
        name="timesheets.projects.create",
        description="Create a project (code uppercased, must be unique).",
        tier=ToolTier.WRITE,
        perm="timesheets.project.manage",
        idempotent=False,
        input_schema=ProjectIn,
        handler=_create_project,
        module_id="timesheets",
    ),
]


def register_timesheets_tools() -> None:
    for tool in _TOOLS:
        if registry.get(tool.name) is None:
            registry.register(tool)


register_timesheets_tools()
