import pytest

from easybiz.core.kernel import tenants
from easybiz.core.kernel.tenants import TenantValidationError


def _validate(**over):
    kw = {
        "slug": "acme",
        "domain": "acme.localhost",
        "owner_email": "owner@acme.test",
        "owner_password": "change-me-now",
        "modules": (),
    }
    kw.update(over)
    return tenants.validate_new_tenant(**kw)


def test_valid_returns_normalized_domain(synced):
    assert _validate(domain="ACME.localhost") == "acme.localhost"


@pytest.mark.parametrize("bad", ["Acme", "1acme", "a", "x" * 32, "ac_me"])
def test_bad_slug_rejected(bad):
    with pytest.raises(TenantValidationError):
        _validate(slug=bad)


@pytest.mark.parametrize("rid", ["public", "platform", "admin", "api", "www"])
def test_reserved_slug_rejected(rid):
    with pytest.raises(TenantValidationError):
        _validate(slug=rid)


@pytest.mark.parametrize(
    "bad", ["https://acme.localhost", "acme.localhost:8000", "acme.localhost/x"]
)
def test_bad_domain_rejected(bad):
    with pytest.raises(TenantValidationError):
        _validate(domain=bad)


def test_missing_password_for_new_owner_rejected():
    with pytest.raises(TenantValidationError):
        _validate(owner_password=None)


def test_short_password_rejected():
    with pytest.raises(TenantValidationError):
        _validate(owner_password="short")


def test_unknown_module_rejected(synced):
    with pytest.raises(TenantValidationError):
        _validate(modules=("nope",))


def test_module_missing_its_requires_rejected(synced, monkeypatch):
    from easybiz.core.kernel import registry as reg
    from easybiz.core.kernel.manifest import parse_manifest

    patched = parse_manifest(
        {"id": "demo", "version": "0.1.0", "requires": [{"module": "timesheets"}]},
        package="easybiz.modules.demo",
    )
    monkeypatch.setitem(reg.registry._manifests, "demo", patched)
    with pytest.raises(TenantValidationError):
        _validate(modules=("demo",))
