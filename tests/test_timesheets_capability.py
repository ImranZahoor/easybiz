import datetime
from decimal import Decimal

import pytest
from django_tenants.utils import tenant_context

from easybiz.core.contracts import AttendanceProvider
from easybiz.core.kernel import capabilities, lifecycle

USER = "44444444-4444-4444-4444-444444444444"
START = datetime.date(2026, 11, 1)
END = datetime.date(2026, 11, 30)


def _seed(tenant):
    from easybiz.modules.timesheets.models import Entry, EntryStatus, Project

    with tenant_context(tenant):
        p = Project.objects.create(code="CPRJ", name="C")

        def mk(day, hours, status):
            Entry.objects.create(
                user_id=USER,
                project=p,
                work_date=datetime.date(2026, 11, day)
                if day <= 30
                else datetime.date(2026, 12, 15),
                hours=Decimal(hours),
                status=status,
            )

        mk(3, "8.00", EntryStatus.APPROVED)  # counts
        mk(4, "4.50", EntryStatus.APPROVED)  # counts
        mk(5, "8.00", EntryStatus.DRAFT)  # not approved
        mk(6, "8.00", EntryStatus.SUBMITTED)  # not approved
        mk(7, "8.00", EntryStatus.REJECTED)  # not approved
        mk(99, "8.00", EntryStatus.APPROVED)  # approved but out of range (December)


def test_approved_hours_sums_only_in_range_approved(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "timesheets")
    _seed(db_tenant)
    with tenant_context(db_tenant):
        provider = capabilities.get(AttendanceProvider)
        assert provider.approved_hours(USER, START, END) == Decimal("12.50")


def test_capability_unavailable_when_disabled(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "timesheets")
    lifecycle.disable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        assert capabilities.get(AttendanceProvider, optional=True) is None
        with pytest.raises(capabilities.CapabilityUnavailable):
            capabilities.get(AttendanceProvider)
