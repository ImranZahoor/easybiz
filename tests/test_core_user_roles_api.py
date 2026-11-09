from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.models import UserRole
from easybiz.core.tenancy.models import Tenant
from easybiz.core.users import service as users
from tests.test_core_roles_write_api import _limited_token, _owner, _req


def _member(tenant, email, roles=()):
    with tenant_context(tenant):
        u = users.create_user(email, tenant, password="change-me-now")
        if roles:
            iam.set_user_roles(u.id, list(roles))
        return str(u.id)


def test_set_add_remove_roles(synced, provision):
    token = _owner(provision, "ur1")
    tenant = Tenant.objects.get(slug="ur1")
    _req(
        "post",
        "/api/core/roles",
        token,
        "ur1",
        {"name": "viewer", "permissions": ["core.user.read"]},
    )
    uid = _member(tenant, "m@ur1.test")

    r = _req("put", f"/api/core/users/{uid}/roles", token, "ur1", {"roles": ["viewer"]})
    assert r.status_code == 200 and r.json()["roles"] == ["viewer"]
    assert _req("delete", f"/api/core/users/{uid}/roles/viewer", token, "ur1").json()["roles"] == []
    assert _req("post", f"/api/core/users/{uid}/roles/viewer", token, "ur1").json()["roles"] == [
        "viewer"
    ]


def test_assign_escalation_blocked(synced, provision):
    _owner(provision, "ur2")
    tenant = Tenant.objects.get(slug="ur2")
    uid = _member(tenant, "m@ur2.test")
    # a role-manager who lacks '*' cannot hand out the owner role (effective '*')
    limited = _limited_token(tenant, ["core.user.manage", "core.role.read"])
    r = _req("put", f"/api/core/users/{uid}/roles", limited, "ur2", {"roles": ["owner"]})
    assert r.status_code == 422


def test_last_owner_cannot_be_demoted(synced, provision):
    token = _owner(provision, "ur3")
    tenant = Tenant.objects.get(slug="ur3")
    # the provisioned owner is the only owner-holder
    with tenant_context(tenant):
        owner_uid = str(
            UserRole.objects.filter(role__name="owner").values_list("user_id", flat=True)[0]
        )
    assert (
        _req("put", f"/api/core/users/{owner_uid}/roles", token, "ur3", {"roles": []}).status_code
        == 409
    )
    assert (
        _req("delete", f"/api/core/users/{owner_uid}/roles/owner", token, "ur3").status_code == 409
    )
