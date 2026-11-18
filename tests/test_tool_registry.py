import pytest

from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool, ToolRegistry


def _tool(name, desc="d"):
    return Tool(
        name=name,
        description=desc,
        tier=ToolTier.READ,
        perm=None,
        idempotent=True,
        input_schema=None,
        handler=lambda uid, p: name,
    )


def test_register_get_search():
    r = ToolRegistry()
    r.register(_tool("core.modules.list", "list modules"))
    r.register(_tool("core.roles.list", "list roles"))
    assert r.get("core.modules.list").description == "list modules"
    assert {t.name for t in r.search("roles")} == {"core.roles.list"}
    assert {t.name for t in r.search("")} == {"core.modules.list", "core.roles.list"}


def test_duplicate_rejected():
    r = ToolRegistry()
    r.register(_tool("x"))
    with pytest.raises(ValueError):
        r.register(_tool("x"))
