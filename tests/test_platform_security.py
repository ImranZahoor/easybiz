import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_platform_token_roundtrip_scope():
    from easybiz.core.api.platform_security import encode_platform_token
    from easybiz.core.api.security import decode_token

    tok = encode_platform_token("11111111-1111-1111-1111-111111111111")
    assert decode_token(tok)["scope"] == "platform"


def test_create_platform_admin_creates_then_promotes(request):
    from easybiz.core.users.models import User

    request.addfinalizer(
        lambda: User.objects.filter(email__in=["ops@easybiz.test", "old@easybiz.test"]).delete()
    )
    call_command(
        "create_platform_admin", "--email", "ops@easybiz.test", "--password", "change-me-now"
    )
    assert User.objects.get(email="ops@easybiz.test").is_platform_admin is True

    User.objects.create(email="old@easybiz.test")  # pre-existing non-admin
    call_command("create_platform_admin", "--email", "old@easybiz.test")  # promote, no password
    assert User.objects.get(email="old@easybiz.test").is_platform_admin is True


def test_create_platform_admin_new_requires_password():
    with pytest.raises(CommandError):
        call_command("create_platform_admin", "--email", "nopass@easybiz.test")
