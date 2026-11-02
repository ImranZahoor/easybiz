import pytest

from easybiz.core.users import service as users
from easybiz.core.users.models import Membership, User
from easybiz.core.users.service import WeakPassword


def test_create_new_user_requires_password(synced, provision, request):
    tenant = provision(slug="acme")
    request.addfinalizer(lambda: User.objects.filter(email="new@acme.test").delete())
    with pytest.raises(WeakPassword):
        users.create_user("new@acme.test", tenant)  # new account, no password
    with pytest.raises(WeakPassword):
        users.create_user("new@acme.test", tenant, password="short")
    user = users.create_user("new@acme.test", tenant, password="change-me-now")
    assert Membership.objects.filter(user=user, tenant=tenant, is_active=True).exists()


def test_existing_user_reused_without_password(synced, provision):
    provision(slug="acme")
    other = provision(slug="zenith")
    owner = User.objects.get(email="owner@acme.test")
    reused = users.create_user("owner@acme.test", other)  # no password, existing account
    assert reused == owner
    assert Membership.objects.filter(user=owner, tenant=other).exists()
