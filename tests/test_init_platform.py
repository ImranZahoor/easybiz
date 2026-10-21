from django.core.management import call_command

from easybiz.core.tenancy.models import Domain, Tenant


def test_public_tenant_and_domain_exist():
    tenant = Tenant.objects.get(schema_name="public")
    assert tenant.slug == "platform"
    domain = Domain.objects.get(tenant=tenant)
    assert domain.domain == "localhost"
    assert domain.is_primary is True


def test_init_platform_is_idempotent():
    call_command("init_platform", "--domain", "localhost", verbosity=0)
    call_command("init_platform", "--domain", "localhost", verbosity=0)
    assert Tenant.objects.filter(schema_name="public").count() == 1
    assert Domain.objects.filter(domain="localhost").count() == 1
