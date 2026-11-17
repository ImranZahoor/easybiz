from easybiz.core.testing import checks


def test_timesheets_passes_dynamic_checks(synced):
    for fn in (
        checks.check_migrations_reversible,
        checks.check_lifecycle_cycle,
        checks.check_schema_isolation,
        checks.check_handler_idempotency,
        checks.check_gate_404,
        checks.check_optional_dependencies,
    ):
        assert fn("timesheets") == [], fn.__name__


def test_demo_passes_dynamic_checks(synced):
    assert checks.check_lifecycle_cycle("demo") == []
    assert checks.check_gate_404("demo") == []  # demo has no endpoints -> skip -> []
