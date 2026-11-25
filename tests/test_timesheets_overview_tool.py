from datetime import date
from decimal import Decimal

from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.core.tools import service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import registry


def test_overview_tool_registered():
    t = registry.get("timesheets.overview")
    assert t is not None and t.tier == ToolTier.READ and t.perm == "timesheets.entry.read"


def _setup(db_tenant):
    from easybiz.modules.timesheets.enums import EntryStatus
    from easybiz.modules.timesheets.models import Entry, Project

    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission="timesheets.entry.read")
        uid = "77777777-7777-7777-7777-777777777777"
        UserRole.objects.create(user_id=uid, role=role)
        p = Project.objects.create(code="ABC", name="A")
        Entry.objects.create(
            user_id=uid,
            project=p,
            work_date=date(2026, 11, 10),
            hours=Decimal("8"),
            status=EntryStatus.APPROVED,
        )
        return uid


def test_overview_pre_aggregates(synced, db_tenant):
    uid = _setup(db_tenant)
    with tenant_context(db_tenant):
        out = service.invoke(
            "timesheets.overview",
            {"start": "2026-11-01", "end": "2026-11-30", "recent": 5},
            user_id=uid,
        )
        assert out["projects"] == 1
        assert out["approved_hours"] == "8.00" and len(out["recent_entries"]) == 1


def test_overview_recent_capped(synced, db_tenant):
    uid = _setup(db_tenant)
    with tenant_context(db_tenant):
        out = service.invoke(
            "timesheets.overview",
            {"start": "2026-11-01", "end": "2026-11-30", "recent": 10_000},
            user_id=uid,
        )
        assert len(out["recent_entries"]) <= 50
