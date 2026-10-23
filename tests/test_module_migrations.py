def test_fresh_tenant_has_core_tables_but_no_module_tables(db_tenant, tables_in):
    tables = tables_in(db_tenant.schema_name)
    assert {"iam_role", "audit_auditlog", "events_outboxevent"} <= tables
    assert "demo_widget" not in tables  # no TenantModule row => router hides it


def test_module_tables_never_in_public(tables_in):
    assert "demo_widget" not in tables_in("public")
