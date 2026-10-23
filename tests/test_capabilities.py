import pytest
from django_tenants.utils import tenant_context

from easybiz.core.kernel import capabilities, lifecycle


class _Contract:  # stand-in contract type
    pass


class _Unregistered:
    pass


class _Impl:
    pass


def test_capability_only_while_enabled(synced, db_tenant):
    impl = _Impl()
    capabilities.register(_Contract, impl, "demo")
    with tenant_context(db_tenant):
        assert capabilities.get(_Contract, optional=True) is None  # demo not enabled
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        assert capabilities.get(_Contract) is impl


def test_missing_capability_raises(db_tenant):
    with pytest.raises(capabilities.CapabilityUnavailable):
        with tenant_context(db_tenant):
            capabilities.get(_Unregistered)
