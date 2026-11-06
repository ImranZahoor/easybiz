def test_shared_core_tables_exist_in_public(tables_in):
    tables = tables_in("public")
    assert {"tenancy_tenant", "tenancy_domain", "users_user", "users_membership"} <= tables


def test_module_tables_absent_from_public(tables_in):
    assert "timesheets_entry" not in tables_in("public")


def test_module_migrations_recorded_but_tableless_in_public(tables_in):
    # Module migrations are no-op-recorded in public (like core tenant apps), so runserver
    # does not report them as unapplied; the router still keeps the tables out of public.
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    applied = MigrationRecorder(connection).applied_migrations()
    assert ("timesheets", "0001_initial") in applied
    assert "timesheets_project" not in tables_in("public")
