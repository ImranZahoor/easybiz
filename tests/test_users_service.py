from easybiz.core.users import service as users
from easybiz.core.users.models import User


def test_authenticate_requires_credentials_and_membership(synced, provision):
    tenant = provision(slug="acme")  # owner@acme.test / change-me-now, member of acme
    owner = User.objects.get(email="owner@acme.test")
    assert users.authenticate("owner@acme.test", "change-me-now", tenant) == owner
    assert users.authenticate("owner@acme.test", "wrong", tenant) is None
    assert users.authenticate("nobody@acme.test", "change-me-now", tenant) is None

    other = provision(slug="zenith")
    assert users.authenticate("owner@acme.test", "change-me-now", other) is None  # no membership
