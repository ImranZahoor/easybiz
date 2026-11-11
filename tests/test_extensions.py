from django_tenants.utils import tenant_context

from easybiz.core.kernel import extensions, lifecycle


class _G:
    def __init__(self, tag):
        self.tag = tag


def test_only_enabled_contributors(synced, db_tenant):
    extensions.register("demo.p", _G("d"), "demo")
    extensions.register("demo.p", _G("t"), "timesheets")
    lifecycle.enable_module(db_tenant, "demo")  # timesheets not enabled
    with tenant_context(db_tenant):
        assert [g.tag for g in extensions.contributors("demo.p")] == ["d"]


def test_contributors_in_load_order(synced, db_tenant):
    extensions.register("demo.p", _G("t"), "timesheets")
    extensions.register("demo.p", _G("d"), "demo")  # registered after, but demo sorts first
    lifecycle.enable_module(db_tenant, "demo")
    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        assert [g.tag for g in extensions.contributors("demo.p")] == ["d", "t"]


def test_no_tenant_no_contributors():
    extensions.register("demo.p", _G("d"), "demo")
    assert extensions.contributors("demo.p") == []


def test_unknown_point_is_empty():
    assert extensions.contributors("nope") == []
