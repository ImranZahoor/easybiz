from easybiz.core.api import paging
from easybiz.core.iam import service as iam
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.paging_io import PageIn, project
from easybiz.core.tools.registry import Tool, registry
from easybiz.modules.timesheets import commands, queries
from easybiz.modules.timesheets.types import (
    CreateProjectParams,
    EntryOut,
    OverviewIn,
    ProjectIn,
    ProjectOut,
)


def _projects(user_id, params):
    page = paging.paginate(
        queries.projects_queryset(), limit=params.limit, cursor=params.cursor, order_by="code"
    )
    items = [ProjectOut.of(p).model_dump() for p in page["items"]]
    return {"items": project(items, params.fields), "next_cursor": page["next_cursor"]}


def _entries(user_id, params):
    can_all = iam.has_permission(iam.permissions_for(user_id), "timesheets.entry.approve")
    page = paging.paginate(
        queries.entries_queryset(user_id, can_all),
        limit=params.limit,
        cursor=params.cursor,
        order_by="-work_date",
    )
    items = [EntryOut.of(e).model_dump() for e in page["items"]]
    return {"items": project(items, params.fields), "next_cursor": page["next_cursor"]}


def _overview(user_id, params):
    # Scopes intentionally differ: `projects` is tenant-wide, `approved_hours` is always the
    # caller's own, and `recent_entries` follows the entries.list rule (own for a reader, all
    # for an approver). A personal-hours total beside a team-wide recent feed is deliberate.
    can_all = iam.has_permission(iam.permissions_for(user_id), "timesheets.entry.approve")
    limit = max(1, min(params.recent, 50))
    recent = queries.entries_queryset(user_id, can_all).order_by("-work_date")[:limit]
    return {
        "projects": queries.projects_queryset().count(),
        "approved_hours": str(queries.approved_hours(user_id, params.start, params.end)),
        "recent_entries": [
            {"work_date": e.work_date.isoformat(), "hours": str(e.hours), "status": e.status}
            for e in recent
        ],
    }


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
        input_schema=PageIn,
        handler=_projects,
        module_id="timesheets",
    ),
    Tool(
        name="timesheets.entries.list",
        description="Time entries (own for a reader; all for an approver).",
        tier=ToolTier.READ,
        perm="timesheets.entry.read",
        idempotent=True,
        input_schema=PageIn,
        handler=_entries,
        module_id="timesheets",
    ),
    Tool(
        name="timesheets.overview",
        description="Pre-aggregated dashboard: project count, approved hours, recent entries.",
        tier=ToolTier.READ,
        perm="timesheets.entry.read",
        idempotent=True,
        input_schema=OverviewIn,
        handler=_overview,
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
