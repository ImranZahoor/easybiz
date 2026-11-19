from django_tenants.utils import tenant_context

from easybiz.core.iam.models import ApiKey


def test_apikey_row(synced, db_tenant):
    with tenant_context(db_tenant):
        k = ApiKey.objects.create(
            name="ci",
            prefix="abcd1234",
            secret_hash="x" * 64,
            permissions=["core.audit.read"],
            created_by="11111111-1111-1111-1111-111111111111",
        )
        assert k.revoked_at is None and k.expires_at is None
        assert k.permissions == ["core.audit.read"]
