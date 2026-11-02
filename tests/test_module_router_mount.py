def test_timesheets_router_is_mounted():
    from easybiz.core.api import api

    prefixes = [prefix for prefix, _ in api._routers]
    assert any("timesheets" in p for p in prefixes)
