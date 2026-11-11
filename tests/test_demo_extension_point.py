from django_tenants.utils import tenant_context

from easybiz.core.kernel import extensions, lifecycle
from easybiz.modules.demo.greetings import all_greetings


class _Hi:
    def greet(self):
        return "hi"


def test_demo_point_collects_enabled_contributors(synced, db_tenant):
    extensions.register("demo.greeters", _Hi(), "demo")
    with tenant_context(db_tenant):
        assert all_greetings() == []  # demo not enabled yet
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        assert all_greetings() == ["hi"]  # enabled contributor shows up
