import pytest

from easybiz.core.testing import run_module_contract_checks


@pytest.mark.module_contract
@pytest.mark.parametrize("module_id", ["timesheets", "demo"])
def test_shipped_modules_satisfy_contract(synced, module_id):
    assert run_module_contract_checks(module_id) == []


def test_non_reversible_migration_flagged(synced, monkeypatch):
    from easybiz.core.testing import checks

    def boom(*a, **k):
        raise RuntimeError("irreversible")

    monkeypatch.setattr(checks, "_migrate_to_zero_and_back", boom)
    assert checks.check_migrations_reversible("timesheets")  # non-empty failures


def test_check_module_command_exit_code(synced, monkeypatch):
    from django.core.management import CommandError, call_command

    call_command("check_module", "timesheets")  # passes -> exit 0, no raise

    from easybiz.core.kernel.management.commands import check_module as cmd

    monkeypatch.setattr(cmd, "run_module_contract_checks", lambda mid: ["boom"])
    with pytest.raises(CommandError):
        call_command("check_module", "timesheets")  # failures -> CommandError
