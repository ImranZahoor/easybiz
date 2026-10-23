import pytest

from easybiz.core.kernel import tenants
from easybiz.core.kernel.tenants import TenantConflict, TenantValidationError
from easybiz.core.tenancy.models import Domain, Tenant


def test_suspend_resume(synced, provision):
    tenant = provision(slug="acme")
    tenants.suspend(tenant)
    assert Tenant.objects.get(pk=tenant.pk).is_active is False
    with pytest.raises(TenantConflict):
        tenants.suspend(tenant)
    tenants.resume(tenant)
    assert Tenant.objects.get(pk=tenant.pk).is_active is True


def test_add_domain_and_primary_switch(synced, provision):
    tenant = provision(slug="acme")
    tenants.add_domain(tenant, "ACME.example", is_primary=True)
    assert Domain.objects.get(tenant=tenant, domain="acme.example").is_primary is True
    assert Domain.objects.get(tenant=tenant, domain="acme.localhost").is_primary is False
    with pytest.raises(TenantConflict):
        tenants.add_domain(tenant, "acme.example")


def test_remove_domain_keeps_at_least_one_and_promotes(synced, provision):
    tenant = provision(slug="acme")
    tenants.add_domain(tenant, "acme.example")
    tenants.remove_domain(tenant, "acme.localhost")  # removing the primary
    assert tenant.domains.count() == 1
    assert Domain.objects.get(tenant=tenant, domain="acme.example").is_primary is True
    with pytest.raises(TenantConflict):
        tenants.remove_domain(tenant, "acme.example")  # last one


def test_remove_primary_promotes_deterministically(synced, provision):
    tenant = provision(slug="acme")  # acme.localhost is primary, lowest id
    tenants.add_domain(tenant, "b.example")
    tenants.add_domain(tenant, "c.example")
    tenants.remove_domain(tenant, "acme.localhost")
    primary = Domain.objects.get(tenant=tenant, is_primary=True)
    assert primary.domain == "b.example"  # lowest remaining id


def test_delete_requires_suspended_and_confirmation(synced, provision):
    tenant = provision(slug="acme")
    with pytest.raises(TenantConflict):
        tenants.delete_tenant(tenant, "acme")  # not suspended
    tenants.suspend(tenant)
    with pytest.raises(TenantValidationError):
        tenants.delete_tenant(tenant, "wrong")
    tenants.delete_tenant(tenant, "acme")
    assert not Tenant.objects.filter(slug="acme").exists()
