import pytest
from django_tenants.utils import tenant_context

from easybiz.core.kernel import capabilities, lifecycle


class _C:
    pass


class _Impl:
    pass


def test_in_range_provider_returned(synced, db_tenant):
    impl = _Impl()
    capabilities.register(_C, impl, "demo", version="1.3.0")
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        assert capabilities.get(_C, range="^1.0") is impl


def test_out_of_range_provider_unavailable(synced, db_tenant):
    impl = _Impl()
    capabilities.register(_C, impl, "demo", version="2.0.0")
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        assert capabilities.get(_C, range="^1.0", optional=True) is None
        with pytest.raises(capabilities.CapabilityUnavailable):
            capabilities.get(_C, range="^1.0")


def test_provider_meta():
    capabilities.register(_C, _Impl(), "demo", version="1.3.0")
    assert capabilities.provider_meta(_C) == ("demo", "1.3.0")
