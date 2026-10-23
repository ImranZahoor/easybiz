def test_catalog_tables_exist_in_public(tables_in):
    assert {"catalog_module", "catalog_tenantmodule", "catalog_permission"} <= tables_in("public")
