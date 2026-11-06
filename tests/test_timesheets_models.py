import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django_tenants.utils import tenant_context

from easybiz.core.kernel import lifecycle


def _enable(db_tenant):
    lifecycle.enable_module(db_tenant, "timesheets")


def test_status_field_derives_choices_from_enum():
    from easybiz.modules.timesheets.models import Entry, EntryStatus

    assert Entry._meta.get_field("status").choices == EntryStatus.choices  # single source
    assert EntryStatus.DRAFT == "draft"  # str-valued enum serializes transparently


def test_project_and_entry_persist(synced, db_tenant):
    _enable(db_tenant)
    from easybiz.modules.timesheets.models import Entry, EntryStatus, Project

    with tenant_context(db_tenant):
        p = Project.objects.create(code="ALPHA", name="Alpha")
        e = Entry.objects.create(
            user_id="11111111-1111-1111-1111-111111111111",
            project=p,
            work_date=datetime.date(2026, 11, 3),
            hours=Decimal("8.00"),
            status=EntryStatus.DRAFT,
        )
        assert e.status == "draft" and p.code == "ALPHA"


def test_hours_range_constraint(synced, db_tenant):
    _enable(db_tenant)
    from easybiz.modules.timesheets.models import Entry, EntryStatus, Project

    with tenant_context(db_tenant):
        p = Project.objects.create(code="BETA", name="Beta")
        with pytest.raises(IntegrityError):
            Entry.objects.create(
                user_id="22222222-2222-2222-2222-222222222222",
                project=p,
                work_date=datetime.date(2026, 11, 3),
                hours=Decimal("25.00"),
                status=EntryStatus.DRAFT,
            )
