def test_shared_core_tables_exist_in_public(tables_in):
    tables = tables_in("public")
    assert {"tenancy_tenant", "tenancy_domain", "users_user", "users_membership"} <= tables


def test_module_tables_absent_from_public(tables_in):
    assert "timesheets_entry" not in tables_in("public")
