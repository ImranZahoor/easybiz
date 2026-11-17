# F17d — Module System v2: Scaffold, Uninstall, Runbook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish F17 — `startmodule <id>` scaffolds a contract-clean module (worked sample), `uninstall_module <id>` removes a module from the catalog when no tenant uses it, and a runbook documents the rolling module deploy.

**Architecture:** A pure `scaffold.py` generates a module package from string templates (validated id, never overwrites); the `startmodule` command drives it and appends the package to `.env`'s `EASYBIZ_MODULES`. An `uninstall_module` service in `lifecycle.py` refuses while any `TenantModule` row exists (catalog-only; `Module` is `PROTECT`ed) then deletes the `Module` + `Permission` rows; a thin command wraps it. Because a new module's code needs a restart before the running process can load it (D9), the scaffold test proves the generated package is contract-clean via the kit's static checks + manifest-parse, and the generated module carries its own `tests/test_contract.py` that runs the full kit after deploy.

**Tech Stack:** Python 3.13, Django 6.1, django-tenants, `uv`/pytest, stdlib only. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §20 (F17) items 1 (scaffold), 6 (uninstall), 7 (runbook) + acceptance. Completes the F17 slice sequence (a→d).

## Global Constraints

- No new dependencies; templates are string constants in `scaffold.py`.
- A generated module must pass `check_module <id>` without edits: app label == id, table prefix `<id>_` (Django's default `<applabel>_<model>` satisfies it since label == id), a sample endpoint guarded by a *declared* permission, no cross-module imports, a reversible initial migration matching the sample model.
- Id validation reuses the manifest rules (`manifest._ID_RE`, `manifest._RESERVED_IDS`); an existing destination directory is never overwritten.
- `uninstall_module` is catalog-only (public schema); code removal remains a deploy step. It refuses while any tenant holds a `TenantModule` row for the module.
- D9: new module code needs a restart/rolling deploy; enable/disable is instant. The runbook documents this.

## Review Focus

- **`startmodule` refuses to overwrite** an existing destination directory (no clobber of a developer's module). (Task 2.)
- **`startmodule` rejects an invalid or reserved id** (reuses the manifest id rules). (Task 2.)
- **The generated module is contract-clean** — its `manifest.json` parses, `apps.py` label == id, and it has no cross-module imports. (Task 2.)
- **`uninstall_module` refuses while any tenant holds a `TenantModule` row** (does not delete the catalog while in use). (Task 1.)
- **`uninstall_module` removes the `Module` and its `Permission` rows** when no tenant holds it. (Task 1.)

---

### Task 1: `uninstall_module` service + command

**Files:**
- Modify: `easybiz/core/kernel/lifecycle.py` (add `uninstall_module`)
- Create: `easybiz/core/kernel/management/commands/uninstall_module.py`
- Test: `tests/test_uninstall_module.py`

**Interfaces:**
- Consumes: `catalog.models.Module`, `Permission`, `TenantModule`; existing `LifecycleError`.
- Produces:
  - `lifecycle.uninstall_module(module_id)` — if `TenantModule.objects.filter(module_id=module_id).exists()` → raise `LifecycleError`; else `Permission.objects.filter(module_id=module_id).delete()` and `Module.objects.filter(id=module_id).delete()`.
  - `uninstall_module` command — `python manage.py uninstall_module <id>`: calls the service, prints the outcome, raises `CommandError` on `LifecycleError`.

- [ ] **Step 1: Write the failing tests** (use throwaway catalog rows so the real demo/timesheets catalog is untouched)

```python
import pytest
from easybiz.core.catalog.models import Module, Permission, TenantModule
from easybiz.core.kernel import lifecycle

def _throwaway_module():
    m = Module.objects.create(id="scaf", name="Scaf", version="0.1.0", manifest={})
    Permission.objects.create(code="scaf.thing.read", module=m, description="x")
    return m

def test_uninstall_removes_catalog_and_permissions(synced):
    _throwaway_module()
    lifecycle.uninstall_module("scaf")
    assert not Module.objects.filter(id="scaf").exists()
    assert not Permission.objects.filter(module_id="scaf").exists()

def test_uninstall_refuses_while_tenant_has_row(synced, db_tenant):
    m = _throwaway_module()
    TenantModule.objects.create(
        tenant=db_tenant, module=m, status=TenantModule.ENABLED, installed_version="0.1.0"
    )
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.uninstall_module("scaf")
    assert Module.objects.filter(id="scaf").exists()  # untouched

def test_command_exit_code(synced):
    from django.core.management import call_command, CommandError
    _throwaway_module()
    call_command("uninstall_module", "scaf")  # exits 0
    with pytest.raises(CommandError):
        call_command("uninstall_module", "nonexistent-with-no-rows")  # nothing to remove -> see Step 3
```

(Ruling to settle in Step 3: `uninstall_module("nonexistent")` with no `Module` row — treat as a `LifecycleError` ("not in the catalog") so the command exits nonzero, matching the "unknown id" convention of other commands. Adjust the test if you choose a no-op-success instead, and ledger it.)

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_uninstall_module.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the service (raise `LifecycleError` for an unknown module id too) and the command.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/kernel/lifecycle.py easybiz/core/kernel/management/commands/uninstall_module.py tests/test_uninstall_module.py && git commit -m "Add uninstall_module (catalog removal, refuses while in use)"`

---

### Task 2: `startmodule` scaffold + command

**Files:**
- Create: `easybiz/core/kernel/scaffold.py`
- Create: `easybiz/core/kernel/management/commands/startmodule.py`
- Test: `tests/test_startmodule.py`

**Interfaces:**
- Consumes: `manifest._ID_RE`, `manifest._RESERVED_IDS`, `manifest.parse_manifest`, the kit's `checks._scan_imports`.
- Produces:
  - `scaffold.scaffold_module(module_id, *, base_dir, package_root="easybiz.modules", requires=(), optional=()) -> Path` — validates the id (raise `ValueError` on invalid/reserved), refuses if `base_dir/<module_id>` exists (raise `FileExistsError`), writes the worked-sample files, returns the created dir.
  - `scaffold.add_to_env(module_package, env_path) -> bool` — append `module_package` to the `EASYBIZ_MODULES=` line in `env_path` (return True); return False if the file or line is absent.
  - `startmodule` command — `python manage.py startmodule <id> [--requires ...] [--optional ...] [--path easybiz.modules]`: maps `--path` to a base dir, calls `scaffold_module`, calls `add_to_env` on `BASE_DIR/.env` (prints the line to add if it returns False), and prints the post-restart steps (restart, `sync_modules`, `check_module <id>`).
- Generated worked-sample files (all contract-clean):
  - `manifest.json` — `manifest_version: 2`, id/name/version `0.1.0`, `requires`/`optional` from the flags, one permission `<id>.thing.read`, a role `<id>_viewer` holding it, empty provides/consumes/events, one menu item.
  - `apps.py` — `AppConfig` with `name = "<package_root>.<id>"`, `label = "<id>"`.
  - `models.py` — a `Thing` model (`id` UUID pk, `name` CharField(200), `created_at` auto_now_add) → default table `<id>_thing`.
  - `api.py` — a `Router` with `GET /things` guarded by `perm("<id>.thing.read")`, returning a small inline `Schema`.
  - `handlers.py`, `providers.py` — module docstring only (no subscriptions/contributions).
  - `migrations/__init__.py` (empty) and `migrations/0001_initial.py` — hand-templated `CreateModel(Thing, ...)` matching `models.py`.
  - `tests/__init__.py` and `tests/test_contract.py` — `assert run_module_contract_checks("<id>") == []` (runs after the module is deployed + restarted).

- [ ] **Step 1: Write the failing tests** (generate into `tmp_path`; prove contract-clean statically)

```python
import pytest
from pathlib import Path
from easybiz.core.kernel import scaffold
from easybiz.core.kernel.manifest import parse_manifest
from easybiz.core.testing import checks
import json

def test_scaffold_generates_contract_clean_module(tmp_path):
    dest = scaffold.scaffold_module("widgets", base_dir=tmp_path)
    assert (dest / "manifest.json").exists() and (dest / "migrations" / "0001_initial.py").exists()
    manifest = parse_manifest(json.loads((dest / "manifest.json").read_text()))
    assert manifest.id == "widgets" and manifest.manifest_version == 2
    assert 'label = "widgets"' in (dest / "apps.py").read_text()      # app label == id
    assert checks._scan_imports(str(dest), "widgets") == []           # no cross-module imports

def test_scaffold_refuses_overwrite(tmp_path):
    scaffold.scaffold_module("widgets", base_dir=tmp_path)
    with pytest.raises(FileExistsError):
        scaffold.scaffold_module("widgets", base_dir=tmp_path)

def test_scaffold_rejects_bad_id(tmp_path):
    for bad in ("Widgets", "1bad", "core", "auth"):
        with pytest.raises(ValueError):
            scaffold.scaffold_module(bad, base_dir=tmp_path)

def test_add_to_env_appends_package(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EASYBIZ_MODULES=easybiz.modules.timesheets,easybiz.modules.demo\n")
    assert scaffold.add_to_env("easybiz.modules.widgets", env) is True
    assert "easybiz.modules.widgets" in env.read_text()

def test_requires_optional_in_manifest(tmp_path):
    dest = scaffold.scaffold_module("widgets", base_dir=tmp_path, requires=["hr"], optional=["demo"])
    m = parse_manifest(json.loads((dest / "manifest.json").read_text()))
    assert [d for d, _ in m.requires] == ["hr"] and [d for d, _ in m.optional] == ["demo"]
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_startmodule.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `scaffold.py` (templates + `add_to_env`) and the `startmodule` command.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Verify the generated migration matches its model** — generate into a tmp dir and confirm the templated `0001_initial.py` imports/fields match `models.py` (a reviewer reads both; the contract test in the generated module is the runtime proof post-deploy).
- [ ] **Step 6: Commit** — `git add easybiz/core/kernel/scaffold.py easybiz/core/kernel/management/commands/startmodule.py tests/test_startmodule.py && git commit -m "Add startmodule scaffold (worked-sample, contract-clean, no overwrite)"`

---

## Post-implementation
- **Runbook** (spec item 7): create `docs/runbooks/module-deploy.md` — the rolling deploy for new module *code*: scaffold with `startmodule`, build an image containing the new package, deploy, run `upgrade_modules`, then enable per tenant; note the D9 limit (code needs a restart; enable/disable is instant) and `uninstall_module` for retirement.
- Update `README.md` Status with a short F17d paragraph (scaffold + uninstall + runbook) and note **F17 is complete**.
- Run the full suite + `pytest -m module_contract` + `check_module timesheets`/`demo` as a final sanity pass.
- Not core authz — a security review is optional; the standard whole-branch review applies.
