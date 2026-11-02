from django_tenants.utils import tenant_context

from easybiz.core.audit import service as audit
from easybiz.core.audit.models import AuditLog


def test_record_writes_in_tenant_schema(synced, db_tenant):
    with tenant_context(db_tenant):
        audit.record(actor_id=None, action="thing.done", entity="thing", entity_id="1")
        assert AuditLog.objects.filter(action="thing.done", entity_id="1").exists()
