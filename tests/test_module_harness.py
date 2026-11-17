from django.db import connection
from django_tenants.utils import tenant_context  # noqa: F401 (imported for parity with kit usage)

from easybiz.core.kernel import state
from easybiz.core.tenancy.models import Tenant
from easybiz.core.testing.harness import module_harness


def test_harness_enables_module_then_tears_down(synced):
    with module_harness("timesheets") as tenant:
        schema = tenant.schema_name
        assert "timesheets" in state.enabled_module_ids(tenant)
        with connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_tables WHERE schemaname=%s AND tablename=%s",
                [schema, "timesheets_project"],
            )
            assert cur.fetchone() is not None  # module tables created
    # after exit: schema dropped, tenant row gone
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", [schema])
        assert cur.fetchone() is None
    assert not Tenant.objects.filter(schema_name=schema).exists()
