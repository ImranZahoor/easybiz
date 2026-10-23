import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, UserRole
from easybiz.core.kernel import provisioning, state
from easybiz.core.kernel.tenants import TenantConflict
from easybiz.core.tenancy.models import Domain, Tenant
from easybiz.core.users.models import Membership, User


def test_provision_creates_everything(synced, provision, tables_in):
    tenant = provision(slug="acme", modules=("demo",))
    assert Tenant.objects.filter(slug="acme").exists()
    assert Domain.objects.get(tenant=tenant).is_primary is True
    owner = User.objects.get(email="owner@acme.test")
    assert Membership.objects.filter(user=owner, tenant=tenant).exists()
    assert state.is_enabled(tenant, "demo") is True
    assert "demo_widget" in tables_in(tenant.schema_name)
    with tenant_context(tenant):
        owner_role = Role.objects.get(name="owner")
        assert owner_role.permissions.filter(permission="*").exists()
        assert UserRole.objects.filter(user_id=owner.id, role=owner_role).exists()


def test_two_tenants_are_isolated(synced, provision, tables_in):
    a = provision(slug="acme", modules=("demo",))
    b = provision(slug="zenith", modules=())
    assert "demo_widget" in tables_in(a.schema_name)
    assert "demo_widget" not in tables_in(b.schema_name)


def test_duplicate_slug_conflicts(synced, provision):
    provision(slug="acme")
    with pytest.raises(TenantConflict):
        provision(slug="acme", domain="acme2.localhost", owner_email="o2@acme.test")


def _all_schemas():
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT schema_name FROM information_schema.schemata")
        return {row[0] for row in cur.fetchall()}


def test_rollback_leaves_no_orphan(synced, monkeypatch, request):
    from easybiz.core.kernel import lifecycle

    # unique owner so the leaked-on-rollback user (people are kept, I14) can't
    # collide with other tests; clean it up for hygiene.
    request.addfinalizer(lambda: User.objects.filter(email="owner@rollback.test").delete())

    def _boom(*a, **k):
        raise RuntimeError("enable failed")

    monkeypatch.setattr(lifecycle, "enable_module", _boom)
    with pytest.raises(RuntimeError):
        provisioning.provision_tenant(
            name="Rollback",
            slug="rollback",
            domain="rollback.localhost",
            owner_email="owner@rollback.test",
            owner_password="change-me-now",
            modules=("demo",),
        )
    assert not Tenant.objects.filter(slug="rollback").exists()
    assert "t_rollback" not in _all_schemas()
