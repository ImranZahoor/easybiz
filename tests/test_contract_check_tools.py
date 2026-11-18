from easybiz.core.testing import checks
from easybiz.core.tools import registry as reg
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool


def test_timesheets_tools_pass_check(synced):
    assert checks.check_tools("timesheets") == []


def test_undeclared_tool_permission_flagged(synced):
    reg.registry.register(
        Tool(
            name="timesheets.bad",
            description="d",
            tier=ToolTier.READ,
            perm="timesheets.secret",
            idempotent=True,
            input_schema=None,
            handler=lambda u, p: None,
            module_id="timesheets",
        )
    )
    assert checks.check_tools("timesheets")  # non-empty: undeclared perm


def test_misprefixed_tool_name_flagged(synced):
    reg.registry.register(
        Tool(
            name="wrong.name",
            description="d",
            tier=ToolTier.READ,
            perm=None,
            idempotent=True,
            input_schema=None,
            handler=lambda u, p: None,
            module_id="timesheets",
        )
    )
    assert checks.check_tools("timesheets")  # non-empty: bad prefix
