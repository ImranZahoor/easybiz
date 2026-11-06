def test_record_platform_writes_row(request):  # public schema via autouse fixtures (no `db`)
    from easybiz.core.tenancy.audit import record_platform
    from easybiz.core.tenancy.models import PlatformAuditLog
    from easybiz.core.users.models import User

    actor = User.objects.create(email="ops@easybiz.test", is_platform_admin=True)
    request.addfinalizer(lambda: User.objects.filter(email="ops@easybiz.test").delete())
    request.addfinalizer(lambda: PlatformAuditLog.objects.filter(target="acme").delete())

    row = record_platform(
        actor, "tenant.created", target="acme", detail={"modules": ["timesheets"]}
    )
    assert row.actor_email == "ops@easybiz.test" and row.action == "tenant.created"
    assert row.detail == {"modules": ["timesheets"]}
    assert PlatformAuditLog.objects.filter(target="acme", action="tenant.created").exists()
