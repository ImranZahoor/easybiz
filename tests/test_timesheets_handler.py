import datetime
from decimal import Decimal

from django_tenants.utils import tenant_context

from easybiz.core.events import service as events
from easybiz.core.events.models import OutboxEvent
from easybiz.core.kernel import lifecycle

USER = "33333333-3333-3333-3333-333333333333"


def _seed_entries(tenant):
    from easybiz.modules.timesheets.enums import EntryStatus
    from easybiz.modules.timesheets.models import Entry, Project

    with tenant_context(tenant):
        p = Project.objects.create(code="HPRJ", name="H")
        mk = lambda st: Entry.objects.create(  # noqa: E731 - terse local factory
            user_id=USER,
            project=p,
            work_date=datetime.date(2026, 11, 3),
            hours=Decimal("8.00"),
            status=st,
        )
        return mk(EntryStatus.DRAFT), mk(EntryStatus.SUBMITTED), mk(EntryStatus.APPROVED)


def test_membership_removed_drops_only_drafts_idempotently(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "timesheets")
    from easybiz.modules.timesheets.enums import EntryStatus
    from easybiz.modules.timesheets.models import Entry

    draft, submitted, approved = _seed_entries(db_tenant)
    with tenant_context(db_tenant):
        ev = OutboxEvent.objects.create(
            name="core.membership.removed", producer="core", payload={"user_id": USER}
        )
        events.dispatch_pending()
        assert not Entry.objects.filter(id=draft.id).exists()  # draft gone
        assert Entry.objects.filter(id=submitted.id).exists()  # submitted kept
        assert Entry.objects.filter(id=approved.id).exists()  # approved kept

        # idempotency: a new draft after a redelivery of the same event must survive
        new_draft = Entry.objects.create(
            user_id=USER,
            project_id=submitted.project_id,
            work_date=datetime.date(2026, 11, 4),
            hours=Decimal("4.00"),
            status=EntryStatus.DRAFT,
        )
        ev.status = OutboxEvent.PENDING
        ev.next_attempt_at = ev.created_at
        ev.save(update_fields=["status", "next_attempt_at"])
        events.dispatch_pending()
        assert Entry.objects.filter(id=new_draft.id).exists()  # inbox blocked the re-run
