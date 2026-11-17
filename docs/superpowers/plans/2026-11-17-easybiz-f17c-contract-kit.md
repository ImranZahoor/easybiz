# F17c — Module System v2: Contract Test Kit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reusable contract test kit — `module_harness`, `run_module_contract_checks`, a `check_module <id>` command, and `pytest -m module_contract` — that verifies a module obeys the module contract, runs green against `timesheets`/`demo`, and fails when any rule is deliberately broken.

**Architecture:** `easybiz/core/testing/` holds the kit. `run_module_contract_checks(module_id) -> list[str]` is the single source of truth: it runs **static** checks (pure introspection — manifest/app-label, endpoint-permissions-declared, subscriptions-have-handlers, no-cross-import AST scan, no-cross-FK + table-prefix) and **dynamic** checks (via `module_harness`, which provisions a throwaway tenant — migrations-reversible, lifecycle cycle, schema isolation, handler-wiring idempotency, gate-404, optional-dep matrix). It returns a list of human-readable failure strings (empty = pass). `check_module` prints them; `pytest -m module_contract` asserts zero against installed modules and runs negative tests against deliberately-broken inputs.

**Tech Stack:** Python 3.13, Django 6.1, django-tenants, django-ninja, PostgreSQL 16 (real DB), `uv`/pytest, stdlib `ast`. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §20 (F17) item 5 and its acceptance criteria. F17d (scaffold/uninstall + runbook) follows.

## Global Constraints

- No new dependencies; the AST scan uses stdlib `ast`, the import-boundary check does not require `import-linter`.
- `run_module_contract_checks` returns `list[str]` (failure messages), never raises for a *contract* violation; it may raise only for a genuinely broken call (unknown module id).
- Dynamic checks provision and tear down their own throwaway tenant schema via `module_harness`; they must leave the DB as they found it.
- Pragmatic depth (user decision): the three hard checks run meaningfully on the real modules without reflection machinery — **isolation** is a structural schema-separation check, **idempotency** verifies handlers are wired through the idempotent dispatcher (deep payload-replay defers to F15 payload schemas), **optional-dep** runs only when a module declares optional deps (none do today → it is a no-op that reports nothing). Full auto-generation is deferred.
- "Payloads match schemas" (part of the events check) defers to **F15** (no payload schemas exist yet); F17c checks event *names* declared + every subscription has a handler.

## Review Focus

- **A module endpoint using an undeclared permission** is flagged (introspect `router.path_operations[*].operations[*].auth[*].permission`; a code under the module's prefix must be declared; `core.*` is allowed). (Task 2.)
- **A module importing another module** (`import easybiz.modules.<other>` / `from easybiz.modules.<other> ...`) is flagged by the AST scan; self and `easybiz.core` are allowed. (Task 2.)
- **A model with a cross-module FK or a mis-prefixed table** is flagged (`_meta.db_table` must start with `<id>_`; every relation's `related_model._meta.app_label` must equal the module id). (Task 2.)
- **A subscription with no registered handler / a non-reversible migration** is flagged (missing-handler via the registry handler map; reversibility via `migrate_schemas <id> zero` then forward in the harness). (Tasks 2 & 3.)
- **Tear-down leak** — a dynamic check that provisions a tenant must drop its schema and rows even when a check fails, leaving no `t_contract*` schema or `Tenant` row behind. (Task 1.)

---

### Task 1: Testing package, harness, and pytest marker

**Files:**
- Create: `easybiz/core/testing/__init__.py`
- Create: `easybiz/core/testing/harness.py`
- Modify: `pytest.ini` (register the `module_contract` marker)
- Test: `tests/test_module_harness.py`

**Interfaces:**
- Produces:
  - `module_harness(module_id, with_=(), without=())` — a context manager yielding a provisioned `Tenant` whose enabled modules are `{module_id} ∪ hard-deps ∪ with_` minus `without`; on exit it drops the schema and deletes the `Tenant`/owner (mirrors the `provision`/`db_tenant` test fixtures, using `provisioning.provision_tenant` with a `contract<n>`-style slug). Tear-down runs in a `finally`.
  - Re-export `run_module_contract_checks` from `checks.py` (Task 2/3) via `__init__.py` once it exists.
- Consumes: `easybiz.core.kernel.provisioning`, `easybiz.core.tenancy.models`, `easybiz.core.kernel.state`.

- [ ] **Step 1: Write the failing test**

```python
from django.db import connection
from django_tenants.utils import tenant_context
from easybiz.core.testing.harness import module_harness
from easybiz.core.kernel import state
from easybiz.core.tenancy.models import Tenant

def test_harness_enables_module_then_tears_down(synced):
    with module_harness("timesheets") as tenant:
        schema = tenant.schema_name
        assert "timesheets" in state.enabled_module_ids(tenant)
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_tables WHERE schemaname=%s AND tablename=%s",
                        [schema, "timesheets_project"])
            assert cur.fetchone() is not None            # module tables created
    # after exit: schema dropped, tenant row gone
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", [schema])
        assert cur.fetchone() is None
    assert not Tenant.objects.filter(schema_name=schema).exists()
```

- [ ] **Step 2: Run it, verify it fails** — Run: `uv run pytest tests/test_module_harness.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `module_harness` (a `@contextlib.contextmanager`) and register the marker in `pytest.ini` (`markers = module_contract: module contract-kit checks`).
- [ ] **Step 4: Run it, verify it passes** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/testing tests/test_module_harness.py pytest.ini && git commit -m "Add contract-kit testing package and module_harness"`

---

### Task 2: Static contract checks

**Files:**
- Create: `easybiz/core/testing/checks.py`
- Test: `tests/test_contract_checks_static.py`

**Interfaces:**
- Produces (each returns `list[str]` — failure messages, empty = pass):
  - `check_manifest_and_app_label(module_id)` — manifest loads; `apps.get_app_config(module_id).label == module_id` and `.name == manifest.package`.
  - `check_endpoint_permissions(module_id)` — for the module's Ninja `router` (if any), every `op.auth[*].permission` that starts with `<id>.` must be a declared manifest permission; `core.*` codes are allowed; an undeclared module-prefixed code is a failure.
  - `check_events(module_id)` — via helper `_missing_handlers(manifest)`: every `manifest.subscribes` name has a handler in `registry.handlers_for(name)` (the helper takes a manifest so the negative can feed a synthetic one). Published-event *declaration* is already enforced at publish-time (M5 `EventError`) and name-prefix at parse-time, so the kit does not re-implement those; payload-schema matching defers to F15. This check is the acceptance's "missing handler"/"undeclared event" rule.
  - `check_no_cross_imports(module_id)` — `ast`-scan every `.py` under the module package; any `import`/`from` of `easybiz.modules.<other>` (other ≠ this id) is a failure; `easybiz.core` and self allowed.
  - `check_no_cross_fk_and_prefix(module_id)` — for each model in `apps.get_app_config(module_id).get_models()`: `_meta.db_table` starts with `<id>_`; for each relation field, `field.related_model._meta.app_label == module_id`.
- Consumes: `registry`, `apps`, the module's `api.router` (import guarded — a module may have no `api`).

- [ ] **Step 1: Write the failing tests** (positives against real modules; negatives against crafted inputs)

```python
from easybiz.core.testing import checks

def test_timesheets_passes_static_checks():
    for fn in (checks.check_manifest_and_app_label, checks.check_endpoint_permissions,
               checks.check_events, checks.check_no_cross_imports, checks.check_no_cross_fk_and_prefix):
        assert fn("timesheets") == [], fn.__name__
    assert checks.check_no_cross_imports("demo") == []

def test_cross_import_flagged(tmp_path, monkeypatch):
    # point the scanner at a package dir containing a file that imports another module
    pkg = tmp_path / "badmod"; pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "x.py").write_text("from easybiz.modules.timesheets import queries\n")
    assert checks._scan_imports(str(pkg), "badmod")  # returns offending import(s)

def test_endpoint_permission_undeclared_flagged():
    # a synthetic router op whose perm is not declared by module 'demo'
    from easybiz.core.api.security import perm
    bad = checks._undeclared_endpoint_perms(perms_used={"demo.secret"}, declared={"demo.widget.read"})
    assert bad == {"demo.secret"}

def test_cross_fk_flagged():
    # a throwaway model (app_label set, not installed) with a FK to another app is flagged
    offenders = checks._relation_offenders(_model_with_cross_fk(), module_id="hr")
    assert offenders  # non-empty

def test_missing_handler_flagged():
    from easybiz.core.kernel.manifest import parse_manifest
    m = parse_manifest({"id": "hr", "name": "HR", "version": "1.0.0",
                        "events": {"subscribes": ["core.nonexistent.event"]}})
    assert checks._missing_handlers(m)  # no handler registered -> non-empty
```

(Design the check bodies around small helpers — `_scan_imports(path, self_id)`, `_undeclared_endpoint_perms(perms_used, declared)`, `_relation_offenders(model, module_id)` — so the negatives feed crafted inputs without a full broken module. `_model_with_cross_fk()` defines a throwaway Django model class with `Meta.app_label="hr"` and a `ForeignKey` to a core model, read via `_meta` only (no DB).)

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_contract_checks_static.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the five check functions and their helpers.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/testing/checks.py tests/test_contract_checks_static.py && git commit -m "Add static module-contract checks"`

---

### Task 3: Dynamic contract checks

**Files:**
- Modify: `easybiz/core/testing/checks.py`
- Test: `tests/test_contract_checks_dynamic.py`

**Interfaces:**
- Produces (each `list[str]`, using `module_harness`):
  - `check_migrations_reversible(module_id)` — in a harness tenant, `migrate_schemas <id> zero` then forward; any error is a failure.
  - `check_lifecycle_cycle(module_id)` — enable → disable → `remove_module_data` → re-enable with no error, asserting the module's tables drop on remove and return on re-enable.
  - `check_schema_isolation(module_id)` — provision two harness tenants with the module enabled and a third without; assert each module table exists in the two enabled schemas and is absent from the third (schema-per-tenant isolation; no sample rows needed).
  - `check_handler_idempotency(module_id)` — assert every `manifest.subscribes` handler is registered through the dispatcher path (wired for inbox-idempotent delivery); deep payload-replay deferred to F15.
  - `check_gate_404(module_id)` — if the module has endpoints, hit one on a tenant where the module is disabled via the Django test `Client` and assert `404`; skip when the module exposes no router.
  - `check_optional_dependencies(module_id)` — for each optional dep, run `module_harness(with_=[dep])` and `module_harness(without=[dep])` and assert enable succeeds in both; reports nothing when there are no optional deps.
- Consumes: Task 1 `module_harness`, `lifecycle`, `call_command`, Django test `Client`.

- [ ] **Step 1: Write the failing tests**

```python
from easybiz.core.testing import checks

def test_timesheets_passes_dynamic_checks(synced):
    for fn in (checks.check_migrations_reversible, checks.check_lifecycle_cycle,
               checks.check_schema_isolation, checks.check_handler_idempotency,
               checks.check_gate_404, checks.check_optional_dependencies):
        assert fn("timesheets") == [], fn.__name__

def test_demo_passes_dynamic_checks(synced):
    assert checks.check_lifecycle_cycle("demo") == []
    assert checks.check_gate_404("demo") == []        # demo has no endpoints -> skip -> []
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_contract_checks_dynamic.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the six dynamic check functions.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/testing/checks.py tests/test_contract_checks_dynamic.py && git commit -m "Add dynamic module-contract checks via module_harness"`

---

### Task 4: Orchestration, command, pytest marker, and negative suite

**Files:**
- Modify: `easybiz/core/testing/checks.py` (add `run_module_contract_checks`)
- Modify: `easybiz/core/testing/__init__.py` (export `run_module_contract_checks`, `module_harness`)
- Create: `easybiz/core/kernel/management/commands/check_module.py`
- Create: `tests/test_module_contract.py` (the `module_contract`-marked suite + the migration/command negatives)
- Test: the file above

**Negative coverage (acceptance's six rules):** five are already pinned by Task 2's static tests (cross-import, cross-FK, undeclared-permission via `_undeclared_endpoint_perms`, and the events facets — missing-handler and malformed/undeclared published event — via `_missing_handlers`/`_malformed_publishes`). The sixth, **non-reversible migration**, is pinned here by monkeypatching the migrate call so it raises, and asserting `check_migrations_reversible` reports a failure (a non-reversible migration surfaces exactly as a `migrate zero` error — no throwaway module/migration needed).

**Interfaces:**
- Produces:
  - `run_module_contract_checks(module_id) -> list[str]` — concatenates every static + dynamic check's failures (each prefixed with the check name); raises `LookupError` only for an unknown module id.
  - `check_module` command — `python manage.py check_module <id>`: prints each failure, raises `CommandError` (non-zero exit) if any, else exits `0`.

- [ ] **Step 1: Write the failing tests**

```python
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
    monkeypatch.setattr(checks, "_migrate_to_zero_and_back", boom)  # simulate a non-reversible migration
    assert checks.check_migrations_reversible("timesheets")  # non-empty failures

def test_check_module_command_exit_code(synced, monkeypatch):
    from django.core.management import call_command, CommandError
    call_command("check_module", "timesheets")          # passes -> exit 0, no raise
    from easybiz.core.kernel.management.commands import check_module as cmd
    monkeypatch.setattr(cmd, "run_module_contract_checks", lambda mid: ["boom"])
    with pytest.raises(CommandError):
        call_command("check_module", "timesheets")       # failures -> CommandError
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_module_contract.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `run_module_contract_checks` (calls every check, flattens failures) and the `check_module` command. Factor the migrate-zero-then-forward call in `check_migrations_reversible` into a named helper `_migrate_to_zero_and_back(module_id, schema)` so the negative can monkeypatch it.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Run `pytest -m module_contract` and the full suite** — Run: `uv run pytest -m module_contract -q && uv run pytest -q` — Expected: the marker selects the contract tests and passes; full suite green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add run_module_contract_checks, check_module command, and the module_contract suite"`

---

## Post-implementation
- Update `README.md` Status with a short F17c paragraph (the kit: `module_harness`, `run_module_contract_checks`, `check_module`, `pytest -m module_contract`; pragmatic depth; payload-schema matching deferred to F15).
- No new events; no Appendix D change. `badmigration` is a test fixture, not a shipped module.
- Not core authz — a security review is optional; the standard whole-branch review applies.
